import json
import re
import time
from contextlib import closing

from django.conf import settings
from openai import OpenAI, OpenAIError

from errors import AnalysisError, BusinessError

INSTRUCTIONS = """\
You help a Korean learner of Japanese read one Japanese sentence.
You receive the sentence, its tokens, each with an id, spans and decided_spans.
Return the Korean translation of the whole sentence in translation_ko.

In spans, answer every span you received. A span is a run of tokens (start_token_id to
end_token_id) that matched a registered grammar pattern, with candidate usages of that pattern.
For each span give its span_id and a verdict:
- "usage": one candidate explains the span with the same reading as your translation. Give its
  candidate_id.
- "not_applicable": there is no grammar to learn at that place (for example の inside a name).
- "unfound": the span has grammar to learn but no candidate explains it. Give new_usage: the
  usage that explains it, which will be added to the same pattern, with usage_name,
  explanation_ko and example_ja written as described for new_patterns below.
- "divergent": the sentence alone can be read with more than one candidate, and nothing in it
  tells which. Give the candidate_id of the candidate with the same reading as your
  translation. Use it only for a span with two or more candidates.
- "unresolved": you cannot tell which candidate explains the span, or the place is outside
  what you can judge.
Use null for candidate_id unless the verdict is "usage" or "divergent", and null for new_usage
unless the verdict is "unfound". Use only candidate ids given for that span.
A span with colloquial_of matched a colloquial form (such as ちゃう) of that standard pattern
(such as てしまう), and its candidates are usages of the standard pattern. For such a span,
explain a new usage as a usage of the standard pattern in general, and write its example_ja
with the standard form, not the colloquial form.

In new_patterns, list grammar points of the sentence that no span explains: particles,
auxiliary verbs, conjugations and grammatical expressions a learner needs. Do not list plain
content words or grammar that a span already explains. decided_spans are grammar points already
explained (start_token_id to end_token_id, with the usage name); do not answer them and do not
list them in new_patterns. For each one:
- tokens: every token of the grammar point in order, from its first to its last token with no
  gap, each with a mark (fix). "lemma" means the same word in any conjugation, "form" means the
  same word in the same conjugated form, "any" means any single token. The first and last
  tokens cannot be "any".
- pattern_name: a short name of the pattern, such as ている or 名詞+で.
- usage_name: a short Korean name of this usage, such as 진행.
- explanation_ko: a Korean explanation of the usage in general, so that it fits every sentence
  with this usage. Do not explain this sentence or its content.
- example_ja: a new short Japanese example sentence with the same grammar and usage. Write a
  sentence of your own. Do not reuse this sentence or its words.
In pattern_name, usage_name and explanation_ko, quote Japanese only from that grammar point's
own tokens. Never quote the whole sentence or long parts of it. Do not write number
placeholders (⟨N1⟩) there. If the sentence has no new grammar to learn, return an empty list.

In words, list the content words a learner may not know (nouns, verbs, adjectives, adverbs and
the like). Particles and auxiliary verbs belong in grammar, not here. Do not list tokens that
are only a number placeholder or a symbol. For each word give its token id (token_id), its
dictionary form (lemma, e.g. 食べる for 食べて), the hiragana reading of that dictionary form
(reading) and a short Korean meaning as used in this sentence (meaning_ko).
For loanwords, including new ones not in dictionaries, keep the katakana in the reading
(コーヒー → コーヒー). For a word written in katakana only for emphasis, give its usual
dictionary form and reading (ヤバい → やばい / やばい). Write readings in kana only.

"""

# 번역(다시 묻기의 번역과 대안 번역 포함)에 숫자 자리표시자를 옮기는 규칙
NUMBER_RULES = """\
Numbers in the sentence are replaced with placeholders such as ⟨N1⟩ and ⟨N2⟩.
Copy every placeholder into each Korean translation exactly as written, with the same brackets
and number. Do not turn a placeholder into digits or words, drop it, or add a placeholder that
is not in the sentence. Example: "⟨N1⟩人で行く" → "⟨N1⟩명이서 간다".
The same translation is reused for sentences that differ only in their numbers, so keep
number notation exactly as in the sentence. Do not turn "⟨N1⟩:⟨N2⟩", "⟨N1⟩/⟨N2⟩" or
"⟨N1⟩.⟨N2⟩" into words such as 시/분, 월/일 or 대: "⟨N1⟩:⟨N2⟩です" → "⟨N1⟩:⟨N2⟩입니다".
"""

# 후보 구간 판정. usage는 후보 하나를 고른 것(decided)이다. divergent는 문장만으로 해석이
# 갈리는 것(주 용법은 번역과 같은 해석), unresolved는 판단하지 못한 것이다(#40).
SPAN_VERDICTS = ("usage", "not_applicable", "unfound", "divergent", "unresolved")
# 새 구문 토큰 표시: lemma 고정 / 활용형도 고정 / 아무거나
TOKEN_FIXES = ("lemma", "form", "any")

# 해석 갈림의 대안. 다시 묻기에서만 받는다. 근거(basis)는 비었는지만 보고 버린다.
ALTERNATIVES_SCHEMA = {
    "anyOf": [
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "translation_ko": {"type": "string"},
                    "basis": {"type": "string"},
                },
                "required": ["candidate_id", "translation_ko", "basis"],
                "additionalProperties": False,
            },
        },
        {"type": "null"},
    ]
}


def span_answers_schema(with_alternatives):
    """후보 구간마다의 판정. 첫 분석과 다시 묻기가 함께 쓰고, 다시 묻기만 대안을 받는다."""
    item = {
        "type": "object",
        "properties": {
            "span_id": {"type": "integer"},
            "verdict": {"type": "string", "enum": list(SPAN_VERDICTS)},
            "candidate_id": {"type": ["integer", "null"]},
            "new_usage": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "usage_name": {"type": "string"},
                            "explanation_ko": {"type": "string"},
                            "example_ja": {"type": "string"},
                        },
                        "required": ["usage_name", "explanation_ko", "example_ja"],
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ]
            },
        },
        "required": ["span_id", "verdict", "candidate_id", "new_usage"],
        "additionalProperties": False,
    }
    if with_alternatives:
        item["properties"]["alternatives"] = ALTERNATIVES_SCHEMA
        item["required"].append("alternatives")
    return {"type": "array", "items": item}


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translation_ko": {"type": "string"},
        "spans": span_answers_schema(False),
        "new_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tokens": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "token_id": {"type": "integer"},
                                "fix": {"type": "string", "enum": list(TOKEN_FIXES)},
                            },
                            "required": ["token_id", "fix"],
                            "additionalProperties": False,
                        },
                    },
                    "pattern_name": {"type": "string"},
                    "usage_name": {"type": "string"},
                    "explanation_ko": {"type": "string"},
                    "example_ja": {"type": "string"},
                },
                "required": [
                    "tokens",
                    "pattern_name",
                    "usage_name",
                    "explanation_ko",
                    "example_ja",
                ],
                "additionalProperties": False,
            },
        },
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "lemma": {"type": "string"},
                    "reading": {"type": "string"},
                    "meaning_ko": {"type": "string"},
                },
                "required": ["token_id", "lemma", "reading", "meaning_ko"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["translation_ko", "spans", "new_patterns", "words"],
    "additionalProperties": False,
}


# 스트림 맨 앞의 translation_ko 문자열(닫는 따옴표까지). 구조화 출력은 스키마의 속성 순서대로
# 쓰므로 번역이 맨 앞에 온다. 이스케이프(\" 등)는 한 덩어리로 건너뛴다.
_TRANSLATION_HEAD = re.compile(r'\A\s*\{\s*"translation_ko"\s*:\s*("(?:[^"\\]|\\.)*")')


class TranslationFirstParser:
    """구조화 출력 JSON 조각을 이어 받아, translation_ko가 끝나는 대로 먼저 꺼낸다."""

    def __init__(self):
        self._text = ""
        self._translation_found = False

    def feed(self, delta):
        """조각을 더한다. 번역 문자열이 이번에 처음 닫혔으면 그 값을, 아니면 None을 돌려준다."""
        self._text += delta
        if self._translation_found:
            return None
        head = _TRANSLATION_HEAD.match(self._text)
        if not head:
            return None
        self._translation_found = True
        try:
            return json.loads(head.group(1))
        except json.JSONDecodeError as e:
            # 정규식은 JSON이 허용하지 않는 이스케이프(\x 등)도 지나보낸다.
            raise BusinessError(AnalysisError.FAILED, "LLM 번역이 JSON 문자열이 아님") from e

    def result(self):
        """다 받은 응답. JSON이 아니면(거절, 끊긴 응답 등) ANALYSIS:FAILED다."""
        try:
            return json.loads(self._text)
        except json.JSONDecodeError as e:
            raise BusinessError(AnalysisError.FAILED, "LLM 응답이 JSON이 아님") from e


# 요청 스레드와 사이드 패널을 오래 붙잡지 않게 시간 상한을 둔다(NFR-14). 스트림에서는 연결과
# 조각 사이 대기마다 적용된다.
# 타임아웃 뒤 재시도하면 이미 과금된 요청을 또 보낼 수 있어 재시도하지 않는다.
TIMEOUT_SECONDS = 30
# 조각이 계속 오면 위 상한에 걸리지 않으므로 스트림 전체에도 상한을 둔다.
STREAM_DEADLINE_SECONDS = 60
# 스트림 뒤 보조 호출(다시 묻기·예문 다시 쓰기)까지 요청 하나가 LLM을 기다리는 전체 상한.
# 클라이언트를 만든 때부터 센다. 운영 Gunicorn 작업자 타임아웃(Dockerfile, 120초)보다 저장할
# 시간만큼 짧아야 하고, 스트림 상한과 조각 대기 상한을 더한 것보다는 길어야 한다.
REQUEST_DEADLINE_SECONDS = 110
MAX_RETRIES = 0


# 스트림이 실패했거나 끝까지 쓰지 못했음을 알리는 이벤트
_FAILED_EVENTS = {"error", "response.failed", "response.incomplete"}


class OpenAILLMClient:
    """요청 하나가 쓰는 클라이언트. 그 요청의 호출들이 마감 시각 하나를 함께 쓴다."""

    def __init__(self):
        self._deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES
        )

    def analyze_stream(self, sentence, tokens, spans, decided_spans):
        """구조화된 출력을 스트림으로 받는다. 번역이 끝나면 ("translation", 번역)을 먼저 넘기고,
        다 받으면 ("result", 검증 전 응답)을 넘긴다. spans는 등록된 패턴에 걸린 구간과 그 후보
        용법이다. decided_spans는 LLM 없이 확정한 구간이라 답을 받지 않고, 새 구문으로 다시 내지
        않게 알리기만 한다.

        SDK 오류(타임아웃·인증·연결 끊김 등), 실패·중단 이벤트, 전체 시간 초과, JSON이 아닌
        응답(거절 등)은 ANALYSIS:FAILED다.
        """
        parser = TranslationFirstParser()
        deadline = time.monotonic() + STREAM_DEADLINE_SECONDS
        try:
            stream = self._client.responses.create(
                model=settings.OPENAI_MODEL,
                instructions=INSTRUCTIONS + NUMBER_RULES,
                input=json.dumps(
                    {
                        "sentence": sentence,
                        "tokens": tokens,
                        "spans": spans,
                        "decided_spans": decided_spans,
                    },
                    ensure_ascii=False,
                ),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "sentence_analysis",
                        "schema": RESPONSE_SCHEMA,
                        "strict": True,
                    }
                },
                stream=True,
            )
            # 사이드 패널이 연결을 끊어 중간에 멈춰도 OpenAI 연결을 닫는다.
            with closing(stream):
                for event in stream:
                    if time.monotonic() > deadline:
                        raise BusinessError(AnalysisError.FAILED, "LLM 스트림 전체 시간 초과")
                    if event.type in _FAILED_EVENTS:
                        raise BusinessError(AnalysisError.FAILED, f"LLM 스트림 실패: {event.type}")
                    if event.type == "response.output_text.delta":
                        translation = parser.feed(event.delta)
                        if translation is not None:
                            yield "translation", translation
        except OpenAIError as e:
            raise BusinessError(AnalysisError.FAILED, "LLM 호출 실패") from e
        yield "result", parser.result()

    def judge_spans(self, sentence, tokens, translation_ko, decided_spans, recheck_spans, spans):
        """후보 구간만 다시 묻는다. 스트림 없이 받은 검증 전 응답을 돌려준다.

        recheck_spans는 첫 응답에서 해석 갈림·미확정이었던 구간, spans는 같은 형태소 조건의
        기존 패턴으로 다시 묻는 구간이다. recheck_spans가 있을 때만 문장 번역을 함께 받는다.
        decided_spans는 해석이 정해진 구간이라 답을 받지 않는다.
        """
        return self._judge(
            "다시 묻기", sentence, tokens, translation_ko, decided_spans, recheck_spans, spans
        )

    def rematch_judge(self, sentence, tokens, translation_ko, decided_spans, spans):
        """패턴 세트 버전이 올라 다시 매칭한 캐시 문장의 새 판별 대상 구간을 판정한다(#41).

        다시 묻기의 같은 형태소 조건 구간과 지침·스키마를 함께 쓰고 호출 목적만 다르다. 번역은
        저장된 것을 주고 받지 않는다. 검증 전 응답을 돌려준다.
        """
        return self._judge("재판정", sentence, tokens, translation_ko, decided_spans, [], spans)

    def _judge(
        self, purpose, sentence, tokens, translation_ko, decided_spans, recheck_spans, spans
    ):
        """다시 묻기와 재판정이 함께 쓰는 구간 판정. recheck_spans가 있을 때만 번역을 받는다."""
        payload = {
            "sentence": sentence,
            "tokens": tokens,
            "translation_ko": translation_ko,
            "decided_spans": decided_spans,
            "recheck_spans": recheck_spans,
            "spans": spans,
        }
        return self._ask(
            purpose,
            JUDGE_INSTRUCTIONS + NUMBER_RULES,
            payload,
            "span_judgement",
            judge_schema(bool(recheck_spans)),
        )

    def rewrite_examples(self, sentence, examples):
        """원문을 베껴 거부된 예문들을 한 번에 다시 쓰게 한다. 검증 전 응답을 돌려준다."""
        payload = {"sentence": sentence, "examples": examples}
        return self._ask(
            "예문 다시 쓰기", REWRITE_INSTRUCTIONS, payload, "example_rewrite", REWRITE_SCHEMA
        )

    def _ask(self, purpose, instructions, payload, name, schema):
        """구조화된 출력을 스트림 없이 받는다.

        요청 마감 시각까지 남은 시간만 기다리고, 이미 지났으면 보내지 않는다. SDK 오류, 끝까지
        쓰지 못한 응답, JSON이 아닌 응답(거절 등)은 ANALYSIS:FAILED다.
        """
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise BusinessError(AnalysisError.FAILED, f"LLM {purpose} 전에 요청 시간 초과")
        try:
            response = self._client.responses.create(
                timeout=min(TIMEOUT_SECONDS, remaining),
                model=settings.OPENAI_MODEL,
                instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": name,
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
        except OpenAIError as e:
            raise BusinessError(AnalysisError.FAILED, f"LLM {purpose} 호출 실패") from e
        if response.status != "completed":
            raise BusinessError(AnalysisError.FAILED, f"LLM {purpose} 실패: {response.status}")
        try:
            return json.loads(response.output_text)
        except json.JSONDecodeError as e:
            raise BusinessError(AnalysisError.FAILED, f"LLM {purpose} 응답이 JSON이 아님") from e


# 첫 응답의 해석 갈림·미확정 구간과, 같은 형태소 조건의 패턴이 이미 있는 구간을 한 번에 다시
# 묻는 지침(#40). 이 호출이 마지막이라 여기서 받은 해석 갈림·미확정은 다시 묻지 않는다.
JUDGE_INSTRUCTIONS = """\
You help a Korean learner of Japanese read one Japanese sentence.
You receive the sentence, its tokens, each with an id, its Korean translation (translation_ko),
decided_spans, recheck_spans and spans. A span is a run of tokens (start_token_id to
end_token_id) that matched a registered grammar pattern, with candidate usages of that pattern.
decided_spans are already explained (with the usage name). Do not answer them, and keep their
reading as it is.
Answer every span in recheck_spans and in spans, each by its span_id. Give a verdict:
- "usage": one candidate explains the span. Give its candidate_id.
- "not_applicable": there is no grammar to learn at that place.
- "unfound": only for spans in spans. The span has grammar to learn but no candidate explains
  it. Give new_usage: a short Korean name of the usage (usage_name), a Korean explanation of the
  usage in general so that it fits every sentence with this usage, not of this sentence
  (explanation_ko), and a new short Japanese example sentence of your own with the same usage
  (example_ja).
- "divergent": the sentence alone can really be read with more than one candidate. Give the
  candidate_id of the main reading and, in alternatives, each other candidate that also fits:
  its candidate_id, the Korean translation of the whole sentence read that way
  (translation_ko), and basis: in Korean, what earlier context would make that reading right.
- "unresolved": you cannot tell which candidate explains the span, or you cannot write a basis
  for the other readings.
If something in the sentence decides the reading, choose one candidate with "usage". Use
"divergent" only when the readings truly split, and write a basis for every alternative.
Use null for candidate_id unless the verdict is "usage" or "divergent", null for new_usage
unless the verdict is "unfound", and null for alternatives unless the verdict is "divergent".
Use only candidate ids given for that span. An alternative must be a candidate other than the
main one, and its translation must differ from the translation of the whole sentence.
A span with colloquial_of matched a colloquial form (such as ちゃう) of that standard pattern
(such as てしまう), and its candidates are usages of the standard pattern. For such a span,
explain a new usage as a usage of the standard pattern in general, and write its example_ja
with the standard form, not the colloquial form.
If you receive recheck_spans, also return in translation_ko the Korean translation of the
whole sentence with your main readings.
In usage_name and explanation_ko, quote Japanese only from that span's own tokens. Never quote
the whole sentence or long parts of it. Do not write number placeholders (⟨N1⟩) there.
"""


def judge_schema(with_translation):
    """다시 묻기 응답. 첫 응답의 해석 갈림·미확정 구간을 다시 물을 때만 번역을 받는다."""
    properties = {"spans": span_answers_schema(True)}
    if with_translation:
        properties = {"translation_ko": {"type": "string"}, **properties}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# 원문을 베껴 거부된 새 예문을 다시 쓰게 하는 지침
REWRITE_INSTRUCTIONS = """\
You help build Japanese example sentences for grammar usages.
You receive a Japanese sentence that a learner is reading, and examples. Each example has an
id (example_id), a grammar pattern (pattern_name), a usage (usage_name, explanation_ko) and an
example sentence (rejected_example) that was rejected because it copied the learner's sentence.
For each example, write a new short Japanese sentence (example_ja) that uses the same grammar
pattern with the same usage. Write a sentence of your own about a different topic. Do not copy
the learner's sentence or any of its phrases; only the grammar pattern itself may appear in
both. Do not write number placeholders (⟨N1⟩). Answer every example_id you received.
"""

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "example_id": {"type": "integer"},
                    "example_ja": {"type": "string"},
                },
                "required": ["example_id", "example_ja"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["examples"],
    "additionalProperties": False,
}


def get_client():
    return OpenAILLMClient()
