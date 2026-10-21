import pytest

from analysis import llm


class FakeLLMClient:
    """실제 OpenAI 대신 정해 둔 응답을 돌려주고, 받은 요청을 기록한다."""

    def __init__(self):
        self.response = {"translation_ko": "번역"}
        # 테스트가 정하지 않은 칸은 기본값으로 채운다. 칸이 빠진 응답을 시험할 때만 끈다.
        self.fill_defaults = True
        self.error = None
        self.requests = []
        # 응답하기 전에 실행할 일. 호출 도중에 다른 요청이 끼어드는 상황을 만든다.
        self.before_respond = None
        self.result_given = False
        # 같은 형태소 조건의 패턴이 이미 있을 때 다시 묻는 요청과 그 응답
        self.rejudge_requests = []
        self.rejudge_response = {"spans": []}
        # 원문을 베낀 예문을 다시 쓰게 하는 요청과 그 응답. 응답을 정하지 않으면 거부된 예문을
        # 그대로 돌려준다(다시 써도 베낀 경우).
        self.rewrite_requests = []
        self.rewrite_response = None
        self.rewrite_error = None

    def analyze_stream(self, sentence, tokens, spans):
        """실제 클라이언트처럼 번역이 문자열이면 먼저 넘기고, 이어서 응답 전체를 넘긴다."""
        self.requests.append({"sentence": sentence, "tokens": tokens, "spans": spans})
        if self.before_respond:
            before_respond, self.before_respond = self.before_respond, None
            before_respond()
        if self.error:
            raise self.error
        response = self.response
        if self.fill_defaults and isinstance(response, dict):
            response = {"spans": [], "new_patterns": [], "words": [], **response}
        if isinstance(response, dict) and isinstance(response.get("translation_ko"), str):
            yield "translation", response["translation_ko"]
        # 번역을 넘긴 뒤 응답 전체를 넘기기 전까지를 테스트가 볼 수 있게 표시한다.
        self.result_given = True
        yield "result", response

    def judge_spans(self, sentence, tokens, translation_ko, spans):
        self.rejudge_requests.append(
            {
                "sentence": sentence,
                "tokens": tokens,
                "translation_ko": translation_ko,
                "spans": spans,
            }
        )
        if self.error:
            raise self.error
        return self.rejudge_response

    def rewrite_examples(self, sentence, examples):
        self.rewrite_requests.append({"sentence": sentence, "examples": examples})
        if self.error or self.rewrite_error:
            raise self.error or self.rewrite_error
        if self.rewrite_response is not None:
            return self.rewrite_response
        return {
            "examples": [
                {"example_id": e["example_id"], "example_ja": e["rejected_example"]}
                for e in examples
            ]
        }


@pytest.fixture
def fake_llm(monkeypatch):
    client = FakeLLMClient()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    return client
