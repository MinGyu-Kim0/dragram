import pytest

from analysis import llm


class FakeLLMClient:
    """실제 OpenAI 대신 정해 둔 응답을 돌려주고, 받은 요청을 기록한다."""

    def __init__(self):
        self.response = {"translation_ko": "번역"}
        self.error = None
        self.requests = []
        # 응답하기 전에 실행할 일. 호출 도중에 다른 요청이 끼어드는 상황을 만든다.
        self.before_respond = None

    def analyze(self, sentence, tokens):
        self.requests.append({"sentence": sentence, "tokens": tokens})
        if self.before_respond:
            before_respond, self.before_respond = self.before_respond, None
            before_respond()
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def fake_llm(monkeypatch):
    client = FakeLLMClient()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    return client
