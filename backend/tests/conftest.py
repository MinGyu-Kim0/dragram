import pytest

from analysis import llm


class FakeLLMClient:
    """실제 OpenAI 대신 정해 둔 응답을 돌려주고, 받은 요청을 기록한다."""

    def __init__(self):
        self.response = {"translation_ko": "번역"}
        self.requests = []

    def analyze(self, sentence, tokens):
        self.requests.append({"sentence": sentence, "tokens": tokens})
        return self.response


@pytest.fixture
def fake_llm(monkeypatch):
    client = FakeLLMClient()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    return client
