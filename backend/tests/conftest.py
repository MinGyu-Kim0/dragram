import pytest

from analysis import llm, stream


class FakeLLMClient:
    """실제 OpenAI 대신 정해 둔 응답을 돌려주고, 받은 요청을 기록한다."""

    def __init__(self):
        # 실제 클라이언트처럼 호출마다 부르는 사용 기록 함수(get_client가 넘긴다)와 그때 쓸 토큰
        # 수 (입력, 캐시된 입력, 출력)
        self.record = None
        self.usage = (100, 0, 10)
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
        self.rejudge_error = None
        # 원문을 베낀 예문을 다시 쓰게 하는 요청과 그 응답. 응답을 정하지 않으면 거부된 예문을
        # 그대로 돌려준다(다시 써도 베낀 경우).
        self.rewrite_requests = []
        self.rewrite_response = None
        self.rewrite_error = None
        # 패턴 세트 버전이 올라 다시 매칭한 캐시 문장의 새 구간을 판정하는 요청과 그 응답(#41).
        # before_rematch는 응답하기 전에 실행할 일이다.
        self.rematch_requests = []
        self.rematch_response = {"spans": []}
        self.rematch_error = None
        self.before_rematch = None
        # JMdict 뜻의 한국어 뜻을 만드는 요청과 그 응답(#97). 응답을 정하지 않으면 뜻마다
        # '<표제> 뜻'을 돌려준다. before_gloss는 응답하기 전에 실행할 일이다.
        self.gloss_requests = []
        self.gloss_response = None
        self.gloss_error = None
        self.before_gloss = None
        # 사전에 없는 단어의 2단계: 뜻 고르기·만들기(#134). 응답을 정하지 않으면 단어마다
        # 새 뜻 '<사전형> 뜻'을 만든다. before_define은 응답하기 전에 실행할 일이다.
        self.define_requests = []
        self.define_response = None
        self.define_error = None
        self.before_define = None

    def connect(self, record):
        """get_client 대신 쓴다. 이 요청의 사용 기록 함수를 받아 둔다."""
        self.record = record
        return self

    def _recorded(self, purpose, error):
        """보낸 호출 하나를 기록하고, 실패면 그 오류를 낸다."""
        input_tokens, cached_input_tokens, output_tokens = self.usage
        self.record(
            purpose=purpose,
            model="fake-model",
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            success=error is None,
        )
        if error:
            raise error

    def all_requests(self):
        """모든 종류의 LLM 요청 기록(첫 분석, 다시 묻기, 예문 다시 쓰기, 재판정)."""
        return (
            self.requests
            + self.rejudge_requests
            + self.rewrite_requests
            + self.rematch_requests
            + self.gloss_requests
            + self.define_requests
        )

    def forget_requests(self):
        """준비 단계의 요청 기록을 지운다."""
        for requests in (
            self.requests,
            self.rejudge_requests,
            self.rewrite_requests,
            self.rematch_requests,
            self.gloss_requests,
            self.define_requests,
        ):
            requests.clear()

    def analyze_stream(self, sentence, tokens, spans, decided_spans, words, unknown_words):
        """실제 클라이언트처럼 번역이 문자열이면 먼저 넘기고, 이어서 응답 전체를 넘긴다."""
        self.requests.append(
            {
                "sentence": sentence,
                "tokens": tokens,
                "spans": spans,
                "decided_spans": decided_spans,
                "words": words,
                "unknown_words": unknown_words,
            }
        )
        if self.before_respond:
            before_respond, self.before_respond = self.before_respond, None
            before_respond()
        self._recorded("first_response", self.error)
        response = self.response
        if self.fill_defaults and isinstance(response, dict):
            response = {"spans": [], "new_patterns": [], "words": [], "new_words": [], **response}
        if isinstance(response, dict) and isinstance(response.get("translation_ko"), str):
            yield "translation", response["translation_ko"]
        # 번역을 넘긴 뒤 응답 전체를 넘기기 전까지를 테스트가 볼 수 있게 표시한다.
        self.result_given = True
        yield "result", response

    def judge_spans(self, sentence, tokens, translation_ko, decided_spans, recheck_spans, spans):
        self.rejudge_requests.append(
            {
                "sentence": sentence,
                "tokens": tokens,
                "translation_ko": translation_ko,
                "decided_spans": decided_spans,
                "recheck_spans": recheck_spans,
                "spans": spans,
            }
        )
        self._recorded("reask", self.error or self.rejudge_error)
        return self.rejudge_response

    def rematch_judge(self, sentence, tokens, translation_ko, decided_spans, spans):
        self.rematch_requests.append(
            {
                "sentence": sentence,
                "tokens": tokens,
                "translation_ko": translation_ko,
                "decided_spans": decided_spans,
                "spans": spans,
            }
        )
        if self.before_rematch:
            before_rematch, self.before_rematch = self.before_rematch, None
            before_rematch()
        self._recorded("rematch_judge", self.error or self.rematch_error)
        return self.rematch_response

    def rewrite_examples(self, sentence, examples):
        self.rewrite_requests.append({"sentence": sentence, "examples": examples})
        self._recorded("example_rewrite", self.error or self.rewrite_error)
        if self.rewrite_response is not None:
            return self.rewrite_response
        return {
            "examples": [
                {"example_id": e["example_id"], "example_ja": e["rejected_example"]}
                for e in examples
            ]
        }

    def gloss_words(self, senses):
        self.gloss_requests.append(senses)
        if self.before_gloss:
            before_gloss, self.before_gloss = self.before_gloss, None
            before_gloss()
        self._recorded("word_gloss", self.error or self.gloss_error)
        if self.gloss_response is not None:
            return self.gloss_response
        return {
            "senses": [
                {"sense_id": s["sense_id"], "meaning_ko": f"{s['dictionary_form']} 뜻"}
                for s in senses
            ]
        }

    def define_words(self, sentence, items):
        self.define_requests.append({"sentence": sentence, "words": items})
        if self.before_define:
            before_define, self.before_define = self.before_define, None
            before_define()
        self._recorded("word_gloss", self.error or self.define_error)
        if self.define_response is not None:
            return self.define_response
        return {
            "words": [
                {
                    "word_id": item["word_id"],
                    "sense_id": None,
                    "meaning_ko": f"{item['dictionary_form']} 뜻",
                    "sense_tags": [],
                    "word_tags": ["noun"],
                }
                for item in items
            ]
        }


@pytest.fixture(autouse=True)
def inline_analysis(settings, monkeypatch):
    """분석 작업을 큐에 넣는 자리에서 바로 실행한다. 테스트 트랜잭션 안의 데이터를 보도록.

    작업 소식은 요청이 읽기 전에 모두 와 있으므로, 기다릴 소식이 없는 요청은 곧바로 닫는다.
    """
    settings.ANALYSIS_INLINE = True
    # 개발용 작업자(compose의 worker)가 테스트 작업을 가져가지 않게 큐를 다른 DB 번호에 둔다.
    settings.REDIS_URL = settings.REDIS_URL.rsplit("/", 1)[0] + "/15"
    monkeypatch.setattr(stream, "WAIT_SECONDS", 1)


@pytest.fixture
def fake_llm(monkeypatch):
    client = FakeLLMClient()
    monkeypatch.setattr(llm, "get_client", client.connect)
    return client
