"""분석 API: 입력 검사, 외부 실패(번역 전 502, 번역 뒤 error 이벤트), 우리 코드 버그(500)."""

import pytest

from analysis.models import SentenceAnalysis
from analysis.views import MAX_TEXT_LENGTH
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, saved_analyses

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


def test_llm_error_fails_the_sentence(client, fake_llm):
    # LLM 클라이언트는 타임아웃 등 외부 실패를 ANALYSIS:FAILED로 알린다(test_llm_client).
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert saved_analyses().count() == 0


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


def test_text_over_the_length_limit_is_rejected_before_analysis(client, fake_llm):
    # 캐시 요청은 토큰을 쓰지 않아 하루 한도로 막히지 않는다. 길이로 저장량과 분석 비용을 막는다.
    fake_llm.response = {"translation_ko": "고양이"}
    assert analyze(client, "猫" * MAX_TEXT_LENGTH).status_code == 200

    response = client.post(
        "/api/analyses/", {"text": "猫" * (MAX_TEXT_LENGTH + 1)}, content_type="application/json"
    )

    assert response.status_code == 413
    assert response.json() == {"error": "ANALYSIS:TEXT_TOO_LONG"}
    assert SentenceAnalysis.objects.count() == 1
