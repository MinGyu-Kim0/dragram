import json
from types import SimpleNamespace

import openai
import pytest

from analysis import llm
from analysis.llm import OpenAILLMClient, TranslationFirstParser
from errors import AnalysisError, BusinessError


@pytest.fixture
def llm_client(settings):
    # 실제 OpenAI는 부르지 않는다. SDK 호출(responses.create)만 바꿔 끼운다.
    settings.OPENAI_API_KEY = "test-key"
    return OpenAILLMClient()


def stream_with(llm_client, monkeypatch, create):
    monkeypatch.setattr(llm_client._client.responses, "create", create)


def deltas(*texts):
    """SDK 스트림 이벤트 대신 쓰는 출력 텍스트 조각 이벤트들"""
    return [SimpleNamespace(type="response.output_text.delta", delta=text) for text in texts]


def stream_of(events):
    """SDK 스트림처럼 close가 있는 이벤트 스트림"""
    yield from events


def test_stream_gives_translation_first_and_then_the_whole_result(llm_client, monkeypatch):
    stream_with(
        llm_client,
        monkeypatch,
        lambda **kwargs: (
            stream_of(deltas('{"translation_ko": "번역"', ', "grammar": []}'))
            if kwargs.get("stream")
            else None
        ),
    )

    assert list(llm_client.analyze_stream("文", [], [], [])) == [
        ("translation", "번역"),
        ("result", {"translation_ko": "번역", "grammar": []}),
    ]


def test_openai_error_becomes_analysis_failure(llm_client, monkeypatch):
    # 타임아웃·인증·속도 제한 등 SDK 예외는 모두 OpenAIError를 상속한다.
    def fail(**_):
        raise openai.OpenAIError("timeout")

    stream_with(llm_client, monkeypatch, fail)

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], [], []))
    assert raised.value.error_code == AnalysisError.FAILED


def test_openai_error_in_the_middle_of_the_stream_becomes_analysis_failure(llm_client, monkeypatch):
    def events():
        yield from deltas('{"translation_ko": "번역"')
        raise openai.OpenAIError("connection reset")

    stream_with(llm_client, monkeypatch, lambda **_: events())

    stream = llm_client.analyze_stream("文", [], [], [])
    assert next(stream) == ("translation", "번역")
    with pytest.raises(BusinessError) as raised:
        next(stream)
    assert raised.value.error_code == AnalysisError.FAILED


@pytest.mark.parametrize("event_type", ["error", "response.failed", "response.incomplete"])
def test_failed_stream_event_becomes_analysis_failure(llm_client, monkeypatch, event_type):
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of(
            [*deltas('{"translation_ko": "번역"'), SimpleNamespace(type=event_type)]
        ),
    )

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], [], []))
    assert raised.value.error_code == AnalysisError.FAILED


@pytest.mark.parametrize("output_text", ["", "not json"])
def test_output_that_is_not_json_becomes_analysis_failure(llm_client, monkeypatch, output_text):
    stream_with(llm_client, monkeypatch, lambda **_: stream_of(deltas(output_text)))

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], [], []))
    assert raised.value.error_code == AnalysisError.FAILED


def feed_all(parser, chunks):
    """조각을 차례로 넣고, 번역이 처음 나온 조각 번호와 번역을 돌려준다."""
    found = None
    for i, chunk in enumerate(chunks):
        translation = parser.feed(chunk)
        if translation is not None:
            assert found is None, "번역은 한 번만 나온다"
            found = (i, translation)
    return found


def test_translation_comes_out_as_soon_as_its_string_closes():
    parser = TranslationFirstParser()
    chunks = ['{"transla', 'tion_ko": "나는 ', '학생입니다."', ', "grammar": [', "]}"]

    assert feed_all(parser, chunks) == (2, "나는 학생입니다.")
    assert parser.result() == {"translation_ko": "나는 학생입니다.", "grammar": []}


def test_escaped_quote_does_not_end_the_translation_early():
    parser = TranslationFirstParser()
    # 조각이 이스케이프 가운데(\ 와 ")에서 끊긴다.
    chunks = ['{"translation_ko": "그는 \\', '"간다\\"', ' \\u3042"', ', "words": []}']

    assert feed_all(parser, chunks) == (2, '그는 "간다" あ')


def test_result_that_is_not_json_becomes_analysis_failure():
    parser = TranslationFirstParser()
    parser.feed('{"translation_ko": "번역", "gram')

    with pytest.raises(BusinessError) as raised:
        parser.result()
    assert raised.value.error_code == AnalysisError.FAILED


def test_translation_with_invalid_escape_becomes_analysis_failure():
    parser = TranslationFirstParser()

    with pytest.raises(BusinessError) as raised:
        parser.feed('{"translation_ko": "잘못된 \\x 이스케이프"')
    assert raised.value.error_code == AnalysisError.FAILED


def test_stream_longer_than_the_total_deadline_becomes_analysis_failure(llm_client, monkeypatch):
    # 조각이 계속 와서 조각 사이 타임아웃에는 걸리지 않아도 전체 시간 상한에서 멈춘다.
    now = iter(range(0, 1000, 25))
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of(deltas('{"translation_ko": "번역"', *[" "] * 10, "}")),
    )

    stream = llm_client.analyze_stream("文", [], [], [])
    assert next(stream) == ("translation", "번역")
    with pytest.raises(BusinessError) as raised:
        next(stream)
    assert raised.value.error_code == AnalysisError.FAILED


def test_request_carries_sentence_tokens_and_candidate_spans(llm_client, monkeypatch):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return stream_of(deltas('{"translation_ko": "번역"}'))

    stream_with(llm_client, monkeypatch, create)
    tokens = [{"id": 0, "surface": "は"}]
    spans = [
        {
            "span_id": 0,
            "start_token_id": 0,
            "end_token_id": 0,
            "candidates": [{"candidate_id": 1, "name": "주제", "explanation_ko": "설명"}],
        }
    ]

    decided = [{"start_token_id": 0, "end_token_id": 0, "name": "주제"}]

    list(llm_client.analyze_stream("は", tokens, spans, decided))

    [request] = requests
    assert json.loads(request["input"]) == {
        "sentence": "は",
        "tokens": tokens,
        "spans": spans,
        "decided_spans": decided,
    }


def judge_with(llm_client, monkeypatch, response):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response

    stream_with(llm_client, monkeypatch, create)
    return requests


SPANS = [
    {
        "span_id": 0,
        "start_token_id": 0,
        "end_token_id": 0,
        "candidates": [{"candidate_id": 1, "name": "주제", "explanation_ko": "설명"}],
    }
]


def test_judge_spans_sends_sentence_translation_and_spans_and_returns_the_answer(
    llm_client, monkeypatch
):
    answer = '{"spans": [{"span_id": 0, "verdict": "usage", "candidate_id": 1, "new_usage": null}]}'
    requests = judge_with(
        llm_client, monkeypatch, SimpleNamespace(status="completed", output_text=answer)
    )
    tokens = [{"id": 0, "surface": "は"}]

    result = llm_client.judge_spans("は", tokens, "는", [], [], SPANS)

    assert result == json.loads(answer)
    [request] = requests
    assert json.loads(request["input"]) == {
        "sentence": "は",
        "tokens": tokens,
        "translation_ko": "는",
        "decided_spans": [],
        "recheck_spans": [],
        "spans": SPANS,
    }
    assert request["text"]["format"]["strict"] is True
    # 같은 조건 구간만 다시 물으면 번역을 받지 않는다.
    assert request["text"]["format"]["schema"]["required"] == ["spans"]
    assert request["timeout"] == llm.TIMEOUT_SECONDS


def test_judge_spans_asks_for_the_translation_only_when_rechecking(llm_client, monkeypatch):
    answer = '{"translation_ko": "는", "spans": []}'
    requests = judge_with(
        llm_client, monkeypatch, SimpleNamespace(status="completed", output_text=answer)
    )
    decided = [{"start_token_id": 0, "end_token_id": 0, "name": "주제"}]

    llm_client.judge_spans("は", [], "는", decided, SPANS, [])

    [request] = requests
    assert json.loads(request["input"])["decided_spans"] == decided
    assert json.loads(request["input"])["recheck_spans"] == SPANS
    assert request["text"]["format"]["schema"]["required"] == ["translation_ko", "spans"]


@pytest.mark.parametrize(
    "response",
    [
        openai.OpenAIError("timeout"),
        SimpleNamespace(status="incomplete", output_text='{"spans": []}'),
        SimpleNamespace(status="completed", output_text="not json"),
    ],
)
def test_judge_spans_failure_becomes_analysis_failure(llm_client, monkeypatch, response):
    judge_with(llm_client, monkeypatch, response)

    with pytest.raises(BusinessError) as raised:
        llm_client.judge_spans("は", [], "는", [], [], SPANS)
    assert raised.value.error_code == AnalysisError.FAILED


def test_follow_up_call_waits_only_until_the_request_deadline(settings, monkeypatch):
    # 요청 하나의 호출들이 함께 쓰는 마감 시각까지 남은 시간만 기다린다.
    settings.OPENAI_API_KEY = "test-key"
    now = iter([0, llm.REQUEST_DEADLINE_SECONDS - 10])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    llm_client = OpenAILLMClient()
    answer = '{"spans": []}'
    requests = judge_with(
        llm_client, monkeypatch, SimpleNamespace(status="completed", output_text=answer)
    )

    llm_client.judge_spans("は", [], "는", [], [], SPANS)

    [request] = requests
    assert request["timeout"] == 10


def test_follow_up_call_after_the_request_deadline_is_not_sent(settings, monkeypatch):
    settings.OPENAI_API_KEY = "test-key"
    now = iter([0, llm.REQUEST_DEADLINE_SECONDS])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    llm_client = OpenAILLMClient()
    requests = judge_with(
        llm_client, monkeypatch, SimpleNamespace(status="completed", output_text="{}")
    )

    with pytest.raises(BusinessError) as raised:
        llm_client.rewrite_examples("文", EXAMPLES)
    assert raised.value.error_code == AnalysisError.FAILED
    assert requests == []


EXAMPLES = [
    {
        "example_id": 0,
        "pattern_name": "ている",
        "usage_name": "진행",
        "explanation_ko": "동작이 이어지고 있다",
        "rejected_example": "昨日図書館で本を見ている",
    }
]


def test_rewrite_examples_sends_sentence_and_rejected_examples_and_returns_the_answer(
    llm_client, monkeypatch
):
    answer = '{"examples": [{"example_id": 0, "example_ja": "雨が降っている"}]}'
    requests = judge_with(
        llm_client, monkeypatch, SimpleNamespace(status="completed", output_text=answer)
    )

    result = llm_client.rewrite_examples("昨日図書館で本を読んでいる", EXAMPLES)

    assert result == json.loads(answer)
    [request] = requests
    assert json.loads(request["input"]) == {
        "sentence": "昨日図書館で本を読んでいる",
        "examples": EXAMPLES,
    }
    assert request["text"]["format"]["strict"] is True


@pytest.mark.parametrize(
    "response",
    [
        openai.OpenAIError("timeout"),
        SimpleNamespace(status="incomplete", output_text='{"examples": []}'),
        SimpleNamespace(status="completed", output_text="not json"),
    ],
)
def test_rewrite_examples_failure_becomes_analysis_failure(llm_client, monkeypatch, response):
    judge_with(llm_client, monkeypatch, response)

    with pytest.raises(BusinessError) as raised:
        llm_client.rewrite_examples("文", EXAMPLES)
    assert raised.value.error_code == AnalysisError.FAILED
