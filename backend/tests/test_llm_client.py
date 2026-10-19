from types import SimpleNamespace

import openai
import pytest

from analysis.llm import OpenAILLMClient
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
