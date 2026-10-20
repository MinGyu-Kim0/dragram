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

    assert list(llm_client.analyze_stream("文", [], [])) == [
        ("translation", "번역"),
        ("result", {"translation_ko": "번역", "grammar": []}),
    ]


def test_openai_error_becomes_analysis_failure(llm_client, monkeypatch):
    # 타임아웃·인증·속도 제한 등 SDK 예외는 모두 OpenAIError를 상속한다.
    def fail(**_):
        raise openai.OpenAIError("timeout")

    stream_with(llm_client, monkeypatch, fail)

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], []))
    assert raised.value.error_code == AnalysisError.FAILED


def test_openai_error_in_the_middle_of_the_stream_becomes_analysis_failure(llm_client, monkeypatch):
    def events():
        yield from deltas('{"translation_ko": "번역"')
        raise openai.OpenAIError("connection reset")

    stream_with(llm_client, monkeypatch, lambda **_: events())

    stream = llm_client.analyze_stream("文", [], [])
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
        list(llm_client.analyze_stream("文", [], []))
    assert raised.value.error_code == AnalysisError.FAILED


@pytest.mark.parametrize("output_text", ["", "not json"])
def test_output_that_is_not_json_becomes_analysis_failure(llm_client, monkeypatch, output_text):
    stream_with(llm_client, monkeypatch, lambda **_: stream_of(deltas(output_text)))

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], []))
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

    stream = llm_client.analyze_stream("文", [], [])
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

    list(llm_client.analyze_stream("は", tokens, spans))

    [request] = requests
    assert json.loads(request["input"]) == {"sentence": "は", "tokens": tokens, "spans": spans}
