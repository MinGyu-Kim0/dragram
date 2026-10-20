from types import SimpleNamespace

import openai
import pytest

from analysis.llm import OpenAILLMClient, TranslationFirst
from errors import AnalysisError, BusinessError


@pytest.fixture
def llm_client(settings):
    # 실제 OpenAI는 부르지 않는다. SDK 호출(responses.create)만 바꿔 끼운다.
    settings.OPENAI_API_KEY = "test-key"
    return OpenAILLMClient()


def respond_with(llm_client, monkeypatch, create):
    monkeypatch.setattr(llm_client._client.responses, "create", create)


def test_structured_output_is_parsed(llm_client, monkeypatch):
    respond_with(
        llm_client,
        monkeypatch,
        lambda **_: SimpleNamespace(output_text='{"translation_ko": "번역", "grammar": []}'),
    )

    assert llm_client.analyze("文", []) == {"translation_ko": "번역", "grammar": []}


def test_openai_error_becomes_analysis_failure(llm_client, monkeypatch):
    # 타임아웃·인증·속도 제한 등 SDK 예외는 모두 OpenAIError를 상속한다.
    def fail(**_):
        raise openai.OpenAIError("timeout")

    respond_with(llm_client, monkeypatch, fail)

    with pytest.raises(BusinessError) as raised:
        llm_client.analyze("文", [])
    assert raised.value.error_code == AnalysisError.FAILED


@pytest.mark.parametrize("output_text", ["", "not json"])
def test_output_that_is_not_json_becomes_analysis_failure(llm_client, monkeypatch, output_text):
    respond_with(llm_client, monkeypatch, lambda **_: SimpleNamespace(output_text=output_text))

    with pytest.raises(BusinessError) as raised:
        llm_client.analyze("文", [])
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
    parser = TranslationFirst()
    chunks = ['{"transla', 'tion_ko": "나는 ', '학생입니다."', ', "grammar": [', "]}"]

    assert feed_all(parser, chunks) == (2, "나는 학생입니다.")
    assert parser.result() == {"translation_ko": "나는 학생입니다.", "grammar": []}


def test_escaped_quote_does_not_end_the_translation_early():
    parser = TranslationFirst()
    # 조각이 이스케이프 가운데(\ 와 ")에서 끊긴다.
    chunks = ['{"translation_ko": "그는 \\', '"간다\\"', ' \\u3042"', ', "words": []}']

    assert feed_all(parser, chunks) == (2, '그는 "간다" あ')


def test_result_that_is_not_json_becomes_analysis_failure():
    parser = TranslationFirst()
    parser.feed('{"translation_ko": "번역", "gram')

    with pytest.raises(BusinessError) as raised:
        parser.result()
    assert raised.value.error_code == AnalysisError.FAILED
