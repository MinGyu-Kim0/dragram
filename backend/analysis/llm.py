import json

from django.conf import settings
from openai import OpenAI

INSTRUCTIONS = """\
You translate one Japanese sentence into natural Korean for a Korean learner of Japanese.
You receive the sentence and its tokens, each with an id.
Return only the Korean translation of the whole sentence in translation_ko.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"translation_ko": {"type": "string"}},
    "required": ["translation_ko"],
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
        """구조화된 출력으로 분석을 받는다. 반환값은 검증 전 응답이다."""
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
        return json.loads(response.output_text)


def get_client():
    return OpenAILLMClient()
