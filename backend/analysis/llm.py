import json
import re
import time
from contextlib import closing

from django.conf import settings
from openai import OpenAI, OpenAIError

from errors import AnalysisError, BusinessError

INSTRUCTIONS = """\
You help a Korean learner of Japanese read one Japanese sentence.
You receive the sentence and its tokens, each with an id.
Return the Korean translation of the whole sentence in translation_ko.

In grammar, list the grammar points a learner needs to understand this sentence: particles,
auxiliary verbs, conjugations and grammatical expressions. Do not list plain content words.
For each one, give the ids of its first and last token (start_token_id, end_token_id;
the same id for a single token), a short Korean name (name) and a Korean explanation of how it
works in this sentence (explanation_ko). Interpret each grammar point the same way as your
translation. In name and explanation_ko, quote Japanese only from that grammar point's own
tokens. Never quote the whole sentence or long parts of it. Use only token ids you received.
If the sentence has no grammar to learn (for example a title made only of nouns), return an
empty grammar list.

In words, list the content words a learner may not know (nouns, verbs, adjectives, adverbs and
the like). Particles and auxiliary verbs belong in grammar, not here. Do not list tokens that
are only a number placeholder or a symbol. For each word give its token id (token_id), its
dictionary form (lemma, e.g. 食べる for 食べて), the hiragana reading of that dictionary form
(reading) and a short Korean meaning as used in this sentence (meaning_ko).
For loanwords, including new ones not in dictionaries, keep the katakana in the reading
(コーヒー → コーヒー). For a word written in katakana only for emphasis, give its usual
dictionary form and reading (ヤバい → やばい / やばい). Write readings in kana only.

Numbers in the sentence are replaced with placeholders such as ⟨N1⟩ and ⟨N2⟩.
Copy every placeholder into translation_ko exactly as written, with the same brackets and number.
Do not turn a placeholder into digits or words, drop it, or add a placeholder that is not
in the sentence. Example: "⟨N1⟩人で行く" → "⟨N1⟩명이서 간다".
The same translation is reused for sentences that differ only in their numbers, so keep
number notation exactly as in the sentence. Do not turn "⟨N1⟩:⟨N2⟩", "⟨N1⟩/⟨N2⟩" or
"⟨N1⟩.⟨N2⟩" into words such as 시/분, 월/일 or 대: "⟨N1⟩:⟨N2⟩です" → "⟨N1⟩:⟨N2⟩입니다".
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translation_ko": {"type": "string"},
        "grammar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_token_id": {"type": "integer"},
                    "end_token_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "explanation_ko": {"type": "string"},
                },
                "required": ["start_token_id", "end_token_id", "name", "explanation_ko"],
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
    "required": ["translation_ko", "grammar", "words"],
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
# 조각이 계속 오면 위 상한에 걸리지 않으므로 스트림 전체에도 상한을 둔다. 운영 Gunicorn
# 작업자 타임아웃(Dockerfile)은 이 상한과 조각 대기 상한을 더한 것보다 길어야 한다.
STREAM_DEADLINE_SECONDS = 60
MAX_RETRIES = 0


# 스트림이 실패했거나 끝까지 쓰지 못했음을 알리는 이벤트
_FAILED_EVENTS = {"error", "response.failed", "response.incomplete"}


class OpenAILLMClient:
    def __init__(self):
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES
        )

    def analyze_stream(self, sentence, tokens):
        """구조화된 출력을 스트림으로 받는다. 번역이 끝나면 ("translation", 번역)을 먼저 넘기고,
        다 받으면 ("result", 검증 전 응답)을 넘긴다.

        SDK 오류(타임아웃·인증·연결 끊김 등), 실패·중단 이벤트, 전체 시간 초과, JSON이 아닌
        응답(거절 등)은 ANALYSIS:FAILED다.
        """
        parser = TranslationFirstParser()
        deadline = time.monotonic() + STREAM_DEADLINE_SECONDS
        try:
            stream = self._client.responses.create(
                model=settings.OPENAI_MODEL,
                instructions=INSTRUCTIONS,
                input=json.dumps({"sentence": sentence, "tokens": tokens}, ensure_ascii=False),
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


def get_client():
    return OpenAILLMClient()
