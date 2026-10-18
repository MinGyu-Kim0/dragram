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


class OpenAILLMClient:
    def __init__(self):
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

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
