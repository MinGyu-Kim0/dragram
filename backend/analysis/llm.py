import json

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


# 동기 호출이라 요청 스레드와 사이드 패널을 오래 붙잡지 않게 시간 상한을 둔다(NFR-14).
# 타임아웃 뒤 재시도하면 이미 과금된 요청을 또 보낼 수 있어 재시도하지 않는다.
TIMEOUT_SECONDS = 30
MAX_RETRIES = 0


class OpenAILLMClient:
    def __init__(self):
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES
        )

    def analyze(self, sentence, tokens):
        """구조화된 출력으로 분석을 받는다. 반환값은 검증 전 응답이다.

        SDK 오류(타임아웃·인증 등)와 JSON이 아닌 응답(거절 등)은 ANALYSIS:FAILED다.
        """
        try:
            response = self._client.responses.create(
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
            )
        except OpenAIError as e:
            raise BusinessError(AnalysisError.FAILED, "LLM 호출 실패") from e
        try:
            return json.loads(response.output_text)
        except json.JSONDecodeError as e:
            raise BusinessError(AnalysisError.FAILED, "LLM 응답이 JSON이 아님") from e


def get_client():
    return OpenAILLMClient()
