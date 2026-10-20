"""분석 API: 입력 검사, 외부 실패(스트림 전 502, 스트림 중 error 이벤트), 우리 코드 버그(500)."""

import pytest

from analysis.models import SentenceAnalysis
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "llm_response",
    [
        {"translation_ko": ""},
        {"translation_ko": "   "},
        {"translation_ko": 3},
        {},
        "not an object",
    ],
)
def test_invalid_llm_response_fails_the_sentence(client, fake_llm, llm_response):
    fake_llm.response = llm_response

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}


def test_sentence_too_long_for_morphology_fails_without_calling_llm(client, fake_llm):
    # SudachiPy는 49,149바이트를 넘는 입력을 나누지 못한다.
    response = analyze(client, "あ" * 20000)

    assert response.status_code == 502  # 스트림을 열기 전에 실패한다
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert fake_llm.requests == []


def test_llm_error_fails_the_sentence(client, fake_llm):
    # LLM 클라이언트는 타임아웃 등 외부 실패를 ANALYSIS:FAILED로 알린다(test_llm_client).
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


def test_unexpected_error_is_not_hidden_as_analysis_failure(client, fake_llm):
    # 외부 실패가 아닌 예외(우리 코드의 버그)는 502로 숨기지 않고 그대로 드러낸다.
    fake_llm.error = TypeError("bug")

    with pytest.raises(TypeError):
        analyze(client, "私は学生です。")


def test_text_with_lone_surrogate_is_rejected_without_calling_llm(client, fake_llm):
    # JSON에는 들어올 수 있지만 UTF-8로 인코딩할 수 없는 문자
    response = client.post(
        "/api/analyses/", '{"text": "\\ud800です"}', content_type="application/json"
    )

    assert response.status_code == 400
    assert response.json() == {"error": "ANALYSIS:TEXT_REQUIRED"}
    assert fake_llm.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "  "},
        {"text": 3},
        ["私は学生です。"],
        {"text": "。」"},
        {"text": "\u200b"},
    ],
)
def test_missing_text_is_rejected_without_calling_llm(client, fake_llm, body):
    response = client.post("/api/analyses/", body, content_type="application/json")

    assert response.status_code == 400
    assert response.json() == {"error": "ANALYSIS:TEXT_REQUIRED"}
    assert fake_llm.requests == []
