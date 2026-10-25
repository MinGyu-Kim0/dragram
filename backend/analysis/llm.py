import json
import re
import time
from contextlib import closing

import openai
from django.conf import settings
from openai import OpenAI, OpenAIError

from analysis.jmdict import SENSE_TAG_NAMES, WHOLE_WORD_TAGS
from analysis.models import UsageLog
from errors import AnalysisError, BusinessError

# 새 용법의 대응 표현(#152). 새 구문·미발견·다시 묻기·용법 채우기가 같은 규칙을 쓴다.
KOREAN_EQUIVALENT_RULE = """\
- korean_equivalent: how this usage is usually rendered in Korean, as one short string, for
  the usage in general and not for one sentence. Join several Korean expressions with " · ".
  If the Korean expression depends on the verb or other words, add a short condition with a
  few typical examples in parentheses. Examples: に for time "~에", に for the other party of
  an action "~에게 · ~을/를 (会う·乗る 등)", で for means "~(으)로", が for the subject
  "~이/가 · ~을/를 (好き·できる 등)", ました "~었습니다". Write "" if no Korean expression fits.
"""

INSTRUCTIONS = (
    """\
You help a Korean learner of Japanese read one Japanese sentence.
You receive the sentence, its tokens, each with an id, spans, decided_spans, words and
unknown_words.
Return the Korean translation of the whole sentence in translation_ko.

In spans, answer every span you received. A span is a run of tokens (start_token_id to
end_token_id) that matched a registered grammar pattern, with candidate usages of that pattern.
For each span give its span_id and a verdict:
- "usage": one candidate explains the span with the same reading as your translation. Give its
  candidate_id.
- "not_applicable": there is no grammar to learn at that place (for example の inside a name).
- "unfound": the span has grammar to learn but no candidate explains it. Give new_usage: the
  usage that explains it, which will be added to the same pattern, with usage_name,
  explanation_ko, example_ja and korean_equivalent written as described for new_patterns below.
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
  tokens cannot be "any". Fix only the tokens that form the grammar: particles, auxiliary
  verbs and words that are part of a grammatical expression (such as 居る in ている, or こと and
  出来る in ことができる). Leave out the content of the sentence, such as the noun being
  modified or the verb being conjugated, or mark it "any" when it lies between grammar tokens:
  for 勝ちました list only ます and た. If the grammar point
  cannot be written without fixing such a token as its first or last token, do not list it.
  Do not list structures made only of content words, such as a verb or noun modifying a noun.
- pattern_name: a short name of the pattern, such as ている or 名詞+で.
- usage_name: a short Korean name of this usage, such as 진행.
  Divide usages of a grammar point by its general meanings, as a dictionary or grammar book
  does (for で: place, means, cause, scope, state). Never name a usage after the topic or
  content of this sentence (such as a score or a match result).
- explanation_ko: a Korean explanation of the usage in general, so that it fits every sentence
  with this usage. Do not explain this sentence or its content.
- example_ja: a new short Japanese example sentence with the same grammar and usage. Write a
  sentence of your own. Do not reuse this sentence or its words.
"""
    + KOREAN_EQUIVALENT_RULE
    + """\
In pattern_name, usage_name, explanation_ko and korean_equivalent, quote Japanese only from that
grammar point's own tokens. Never quote the whole sentence or long parts of it. Do not write number
placeholders (⟨N1⟩) there. If the sentence has no new grammar to learn, return an empty list.

In words, answer every token you received in words. Each has candidate senses of that word as
"sense id: English glosses". Give its token_id and the sense_id of the candidate with the
meaning the token has in this sentence. Use only sense ids given for that token.

unknown_words are ids of tokens that are not in the dictionary. In new_words, answer each of
them that is a word a learner can look up: its token_id, its dictionary form as usually
written (dictionary_form) and the reading of that dictionary form in hiragana (reading). Do
not answer names of people, places, works or organizations, or tokens that are not words.

"""
)

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
                            "korean_equivalent": {"type": "string"},
                        },
                        "required": [
                            "usage_name",
                            "explanation_ko",
                            "example_ja",
                            "korean_equivalent",
                        ],
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
                    "korean_equivalent": {"type": "string"},
                },
                "required": [
                    "tokens",
                    "pattern_name",
                    "usage_name",
                    "explanation_ko",
                    "example_ja",
                    "korean_equivalent",
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
                    "sense_id": {"type": "integer"},
                },
                "required": ["token_id", "sense_id"],
                "additionalProperties": False,
            },
        },
        "new_words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "dictionary_form": {"type": "string"},
                    "reading": {"type": "string"},
                },
                "required": ["token_id", "dictionary_form", "reading"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["translation_ko", "spans", "new_patterns", "words", "new_words"],
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
# 클라이언트를 만든 때부터 센다. 분석 작업 시간 제한(analysis/jobs.py, 120초)보다 저장할
# 시간만큼 짧아야 하고, 스트림 상한과 조각 대기 상한을 더한 것보다는 길어야 한다.
REQUEST_DEADLINE_SECONDS = 110
MAX_RETRIES = 0


def _transient(error):
    """다시 보내면 나을 수 있는 SDK 오류(연결 오류, 429, 5xx). 타임아웃은 위 이유로 넣지 않는다."""
    return not isinstance(error, openai.APITimeoutError) and isinstance(
        error, (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)
    )


class _NothingReceived(BusinessError):
    """받은 것 없이 일시 오류로 실패한 호출. 요청 마감 안이면 한 번만 다시 보낸다(#99)."""


# 스트림이 실패했거나 끝까지 쓰지 못했음을 알리는 이벤트
_FAILED_EVENTS = {"error", "response.failed", "response.incomplete"}
# 응답(모델명·토큰 사용량)을 싣고 스트림을 끝내는 이벤트. error 이벤트에는 응답이 없다.
_FINAL_EVENTS = {"response.completed", "response.failed", "response.incomplete"}


class OpenAILLMClient:
    """요청 하나가 쓰는 클라이언트. 그 요청의 호출들이 마감 시각 하나를 함께 쓴다.

    보낸 호출마다 record(purpose, model, input_tokens, cached_input_tokens, output_tokens,
    success, attempt)를 한 번 부른다. 보내지 못했거나 응답이 없으면 토큰은 None이다. 마감이
    지나 보내지 않은 호출은 부르지 않는다.
    """

    def __init__(self, record):
        self._record = record
        self._deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES
        )

    def analyze_stream(self, sentence, tokens, spans, decided_spans, words, unknown_words):
        """구조화된 출력을 스트림으로 받는다. 번역이 끝나면 ("translation", 번역)을 먼저 넘기고,
        다 받으면 ("result", 검증 전 응답)을 넘긴다. spans는 등록된 패턴에 걸린 구간과 그 후보
        용법이다. decided_spans는 LLM 없이 확정한 구간이라 답을 받지 않고, 새 구문으로 다시 내지
        않게 알리기만 한다. words는 JMdict 후보 뜻이 여럿인 토큰과 그 후보다(#96). unknown_words는
        사전에서 못 찾은 토큰 ID로, 사전형·읽기만 받는다(#134).

        SDK 오류(타임아웃·인증·연결 끊김 등), 실패·중단 이벤트, 전체 시간 초과, JSON이 아닌
        응답(거절 등)은 ANALYSIS:FAILED다. 아무것도 받기 전에 일시 오류로 실패했으면 요청 마감
        안에서 한 번 더 보낸다(#99).
        """
        args = (sentence, tokens, spans, decided_spans, words, unknown_words)
        try:
            yield from self._stream(1, *args)
        except _NothingReceived:
            if time.monotonic() >= self._deadline:
                raise
            yield from self._stream(2, *args)

    def _stream(self, attempt, sentence, tokens, spans, decided_spans, words, unknown_words):
        """analyze_stream의 호출 한 번. attempt는 시도 차수다."""
        parser = TranslationFirstParser()
        # 다시 보낸 스트림도 요청 마감을 넘기지 않는다.
        now = time.monotonic()
        deadline = min(now + STREAM_DEADLINE_SECONDS, self._deadline)
        # 사이드 패널이 연결을 끊어 중간에 닫혀도 보낸 호출은 기록한다.
        final, success, received = None, False, False
        try:
            stream = self._client.responses.create(
                timeout=min(TIMEOUT_SECONDS, self._deadline - now),
                model=settings.OPENAI_MODEL,
                instructions=INSTRUCTIONS + NUMBER_RULES,
                input=json.dumps(
                    {
                        "sentence": sentence,
                        "tokens": tokens,
                        "spans": spans,
                        "decided_spans": decided_spans,
                        "words": words,
                        "unknown_words": unknown_words,
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
                    received = True
                    if event.type in _FINAL_EVENTS:
                        final = event.response
                    if time.monotonic() > deadline:
                        raise BusinessError(AnalysisError.FAILED, "LLM 스트림 전체 시간 초과")
                    if event.type in _FAILED_EVENTS:
                        raise BusinessError(AnalysisError.FAILED, f"LLM 스트림 실패: {event.type}")
                    if event.type == "response.output_text.delta":
                        translation = parser.feed(event.delta)
                        if translation is not None:
                            yield "translation", translation
            result = parser.result()
            success = True
        except OpenAIError as e:
            failure = _NothingReceived if not received and _transient(e) else BusinessError
            raise failure(AnalysisError.FAILED, "LLM 호출 실패") from e
        finally:
            self._record_call(UsageLog.Purpose.FIRST_RESPONSE, final, success, attempt)
        yield "result", result

    def judge_spans(self, sentence, tokens, translation_ko, decided_spans, recheck_spans, spans):
        """후보 구간만 다시 묻는다. 스트림 없이 받은 검증 전 응답을 돌려준다.

        recheck_spans는 첫 응답에서 해석 갈림·미확정이었던 구간, spans는 같은 형태소 조건의
        기존 패턴으로 다시 묻는 구간이다. recheck_spans가 있을 때만 문장 번역을 함께 받는다.
        decided_spans는 해석이 정해진 구간이라 답을 받지 않는다.
        """
        return self._judge(
            UsageLog.Purpose.REASK,
            "다시 묻기",
            sentence,
            tokens,
            translation_ko,
            decided_spans,
            recheck_spans,
            spans,
        )

    def rematch_judge(self, sentence, tokens, translation_ko, decided_spans, spans):
        """패턴 세트 버전이 올라 다시 매칭한 캐시 문장의 새 판별 대상 구간을 판정한다(#41).

        다시 묻기의 같은 형태소 조건 구간과 지침·스키마를 함께 쓰고 호출 목적만 다르다. 번역은
        저장된 것을 주고 받지 않는다. 검증 전 응답을 돌려준다.
        """
        return self._judge(
            UsageLog.Purpose.REMATCH_JUDGE,
            "재판정",
            sentence,
            tokens,
            translation_ko,
            decided_spans,
            [],
            spans,
        )

    def _judge(
        self, purpose, label, sentence, tokens, translation_ko, decided_spans, recheck_spans, spans
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
            label,
            JUDGE_INSTRUCTIONS + NUMBER_RULES,
            payload,
            "span_judgement",
            judge_schema(bool(recheck_spans)),
        )

    def rewrite_examples(self, sentence, examples):
        """원문을 베껴 거부된 예문들을 한 번에 다시 쓰게 한다. 검증 전 응답을 돌려준다."""
        payload = {"sentence": sentence, "examples": examples}
        return self._ask(
            UsageLog.Purpose.EXAMPLE_REWRITE,
            "예문 다시 쓰기",
            REWRITE_INSTRUCTIONS,
            payload,
            "example_rewrite",
            REWRITE_SCHEMA,
        )

    def gloss_words(self, senses):
        """JMdict 뜻들의 한국어 뜻을 한 번에 만든다(#97). 검증 전 응답을 돌려준다.

        senses는 뜻마다 sense_id·표제·읽기·pos·영어 뜻·뜻 태그다. 문장은 넘기지 않는다.
        """
        return self._ask(
            UsageLog.Purpose.WORD_GLOSS,
            "한국어 뜻",
            GLOSS_INSTRUCTIONS,
            {"senses": senses},
            "word_gloss",
            GLOSS_SCHEMA,
        )

    def define_words(self, sentence, items):
        """사전에 없는 단어의 뜻을 고르거나 만든다(#134 2단계). 검증 전 응답을 돌려준다.

        items는 단어마다 word_id·token_id·사전형·읽기·후보 뜻('뜻 ID: 뜻')이다.
        """
        return self._ask(
            UsageLog.Purpose.WORD_GLOSS,
            "새 단어 뜻",
            DEFINE_INSTRUCTIONS,
            {"sentence": sentence, "words": items},
            "word_definitions",
            DEFINE_SCHEMA,
        )

    def fill_usages(self, usages):
        """이미 있는 용법의 빈 칸(대응 표현)을 채운다(#152, fill_usages 명령). 검증 전 응답을
        돌려준다.

        usages는 용법마다 usage_id·패턴 이름·용법 이름·설명·예문이다. 문장 원문은 넘기지 않는다.
        """
        return self._ask(
            UsageLog.Purpose.USAGE_FILL,
            "용법 채우기",
            FILL_INSTRUCTIONS,
            {"usages": usages},
            "usage_fill",
            FILL_SCHEMA,
        )

    def _ask(self, purpose, label, instructions, payload, name, schema):
        """구조화된 출력을 스트림 없이 받는다(_ask_once). 일시 오류로 실패했으면 한 번 더
        보낸다(#99). 마감이 지났으면 _ask_once가 보내지 않는다.
        """
        args = (purpose, label, instructions, payload, name, schema)
        try:
            return self._ask_once(1, *args)
        except _NothingReceived:
            return self._ask_once(2, *args)

    def _ask_once(self, attempt, purpose, label, instructions, payload, name, schema):
        """구조화된 출력을 스트림 없이 한 번 받는다. attempt는 시도 차수, purpose는 사용 기록의
        호출 목적, label은 로그용 이름이다.

        요청 마감 시각까지 남은 시간만 기다리고, 이미 지났으면 보내지 않는다. SDK 오류, 끝까지
        쓰지 못한 응답, JSON이 아닌 응답(거절 등)은 ANALYSIS:FAILED다.
        """
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise BusinessError(AnalysisError.FAILED, f"LLM {label} 전에 요청 시간 초과")
        response, success = None, False
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
            if response.status != "completed":
                raise BusinessError(AnalysisError.FAILED, f"LLM {label} 실패: {response.status}")
            try:
                answer = json.loads(response.output_text)
            except json.JSONDecodeError as e:
                raise BusinessError(AnalysisError.FAILED, f"LLM {label} 응답이 JSON이 아님") from e
            success = True
            return answer
        except OpenAIError as e:
            failure = _NothingReceived if _transient(e) else BusinessError
            raise failure(AnalysisError.FAILED, f"LLM {label} 호출 실패") from e
        finally:
            self._record_call(purpose, response, success, attempt)

    def _record_call(self, purpose, response, success, attempt):
        """보낸 호출 하나를 기록한다. response는 SDK 응답이고 받지 못했으면 None이다."""
        model, tokens = settings.OPENAI_MODEL, (None, None, None)
        if response is not None:
            model = response.model
            if (usage := response.usage) is not None:
                tokens = (
                    usage.input_tokens,
                    usage.input_tokens_details.cached_tokens,
                    usage.output_tokens,
                )
        input_tokens, cached_input_tokens, output_tokens = tokens
        self._record(
            purpose=purpose,
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            success=success,
            attempt=attempt,
        )


# 첫 응답의 해석 갈림·미확정 구간과, 같은 형태소 조건의 패턴이 이미 있는 구간을 한 번에 다시
# 묻는 지침(#40). 이 호출이 마지막이라 여기서 받은 해석 갈림·미확정은 다시 묻지 않는다.
JUDGE_INSTRUCTIONS = (
    """\
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
  (explanation_ko), a new short Japanese example sentence of your own with the same usage
  (example_ja), and korean_equivalent as described below.
  Divide usages of a grammar point by its general meanings, as a dictionary or grammar book
  does (for で: place, means, cause, scope, state). Never name a usage after the topic or
  content of this sentence (such as a score or a match result).
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
In usage_name, explanation_ko and korean_equivalent, quote Japanese only from that span's own
tokens. Never quote the whole sentence or long parts of it. Do not write number placeholders
(⟨N1⟩) there.
"""
    + KOREAN_EQUIVALENT_RULE
)


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


# JMdict 뜻의 한국어 뜻을 만드는 지침(#97). 근거는 사전 칸뿐이다.
GLOSS_INSTRUCTIONS = """\
You translate Japanese dictionary senses for a Korean learner of Japanese.
You receive senses. Each has an id (sense_id), the headword (dictionary_form), its reading,
the part of speech code of the word (pos), the English glosses of this sense (gloss_en) and
sense tags. For each sense, write one short Korean meaning (meaning_ko) of that sense only,
as a dictionary would. Join close synonyms with ", " (for example "먹다, 식사하다"). Do not
write explanations, examples, readings or the Japanese headword. Answer every sense_id you
received.
"""

GLOSS_SCHEMA = {
    "type": "object",
    "properties": {
        "senses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sense_id": {"type": "integer"},
                    "meaning_ko": {"type": "string"},
                },
                "required": ["sense_id", "meaning_ko"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["senses"],
    "additionalProperties": False,
}


# 사전에 없는 단어의 2단계(#134). 서버가 다시 찾은 후보에서 고르거나 새 뜻을 만든다.
DEFINE_INSTRUCTIONS = """\
You help a Korean learner of Japanese with words that the dictionary lookup missed.
You receive a Japanese sentence and words of it. Each word has an id (word_id), the token
(token_id), its dictionary form, its reading and candidate senses of a dictionary entry as
"sense id: meaning". The candidates may be empty.
For each word give its word_id and:
- sense_id: the candidate with the meaning the word has in this sentence, or null if no
  candidate fits or there are none.
- meaning_ko: when sense_id is null, one short Korean meaning of the word as used in this
  sentence, written as a dictionary would, not an explanation of the sentence. Otherwise "".
- sense_tags: tags of that meaning from the allowed list, if any.
- word_tags: tags of the whole word from the allowed list (part of speech, verb group, proper
  noun).
Answer every word_id you received.
"""

DEFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word_id": {"type": "integer"},
                    "sense_id": {"type": ["integer", "null"]},
                    "meaning_ko": {"type": "string"},
                    "sense_tags": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(SENSE_TAG_NAMES)},
                    },
                    "word_tags": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(WHOLE_WORD_TAGS)},
                    },
                },
                "required": ["word_id", "sense_id", "meaning_ko", "sense_tags", "word_tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["words"],
    "additionalProperties": False,
}


# 이미 있는 용법의 대응 표현을 채우는 지침(#152). 근거는 용법 칸뿐이다.
FILL_INSTRUCTIONS = (
    """\
You help a Korean learner of Japanese with grammar usages.
You receive usages. Each has an id (usage_id), the grammar pattern (pattern_name), the usage
name (usage_name), its Korean explanation (explanation_ko) and an example sentence
(example_ja, may be null). For each usage give its usage_id and:
"""
    + KOREAN_EQUIVALENT_RULE
    + """\
Do not write number placeholders (⟨N1⟩). Answer every usage_id you received.
"""
)

FILL_SCHEMA = {
    "type": "object",
    "properties": {
        "usages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "usage_id": {"type": "integer"},
                    "korean_equivalent": {"type": "string"},
                },
                "required": ["usage_id", "korean_equivalent"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["usages"],
    "additionalProperties": False,
}


def get_client(record):
    return OpenAILLMClient(record)
