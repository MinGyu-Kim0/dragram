"""분석 API: 결과를 나오는 대로 보내기(줄 단위 JSON 스트림)."""

import json

import pytest

from analysis import worker
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, post, saved_analyses

pytestmark = pytest.mark.django_db


def test_translation_is_sent_before_grammar_and_words(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "먹는다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"), pattern_name="た", usage_name="문법", example_ja="パンを食べた"
            )
        ],
    }

    response = analyze(client, "食べた")

    assert response.response["Content-Type"] == "application/x-ndjson"
    # 응답 전체보다 번역을 먼저 알리는 작업자 쪽은 test_worker에서 본다.
    first, second = response.events
    assert first == {
        "type": "translation",
        "translation_ko": "먹는다",
        "ruby": [{"start": 0, "end": 1, "reading": "た"}],
    }
    assert second["type"] == "analysis"
    assert second["translation_ko"] == "먹는다"
    assert [item["name"] for item in second["grammar"]] == ["문법"]
    assert second["words"] == []


@pytest.fixture
def every_partial(monkeypatch):
    # 번역 앞부분을 모아 보내는 간격을 없애, 넘긴 앞부분을 모두 알린다.
    monkeypatch.setattr(worker, "PARTIAL_INTERVAL_SECONDS", 0)


def partial(text):
    return {"type": "translation_partial", "translation_ko": text}


def test_translation_prefix_grows_before_the_checked_translation(client, fake_llm, every_partial):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    fake_llm.translation_partials = ["나는", "나는 학생"]

    response = analyze(client, "私は学生です。")

    assert response.events[:3] == [partial("나는"), partial("나는 학생")] + [
        {
            "type": "translation",
            "translation_ko": "나는 학생입니다.",
            "ruby": response.events[2]["ruby"],
        }
    ]
    assert response.types()[3:] == ["analysis"]


def test_prefix_holds_back_a_number_until_its_particle_is_settled(client, fake_llm, every_partial):
    # LLM이 고른 조사(는)는 숫자 발음에 맞춰 바뀌므로(1은), 자리표시자 뒤 말이 끝날 때까지
    # 숫자를 보내지 않는다. 덜 온 자리표시자, 없는 번호의 자리표시자도 보내지 않는다.
    fake_llm.response = {"translation_ko": "⟨N1⟩는 홀수다."}
    fake_llm.translation_partials = ["⟨N", "⟨N1⟩", "⟨N1⟩는", "⟨N1⟩는 홀", "⟨N1⟩는 홀 ⟨N2⟩ "]

    response = analyze(client, "1は奇数だ。")

    assert response.events[0] == partial("1은 홀")
    assert response.types() == ["translation_partial", "translation", "analysis"]
    assert response.events[1]["translation_ko"] == "1은 홀수다."


def test_partials_are_sent_at_most_once_per_interval(client, fake_llm, monkeypatch):
    monkeypatch.setattr(worker, "PARTIAL_INTERVAL_SECONDS", 60)
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    fake_llm.translation_partials = ["나는", "나는 학생"]

    response = analyze(client, "私は学生です。")

    assert response.types() == ["translation_partial", "translation", "analysis"]
    assert response.events[0] == partial("나는")


def test_translation_failing_after_its_prefix_ends_in_an_error(client, fake_llm, every_partial):
    # 숫자 자리표시자가 빠진 번역. 앞부분은 이미 보냈어도 저장하지 않고 실패한다.
    fake_llm.response = {"translation_ko": "셋이서 간다."}
    fake_llm.translation_partials = ["셋이서"]

    response = analyze(client, "3人で行く")

    assert response.events == [partial("셋이서"), {"type": "error", "error": "ANALYSIS:FAILED"}]
    assert saved_analyses().count() == 0


def test_failure_before_translation_is_an_error_event(client, fake_llm):
    # LLM 작업은 응답을 시작한 뒤 작업자에서 하므로 상태 코드가 아니라 error 이벤트다(#98).
    # 숫자 자리표시자가 빠진 번역
    fake_llm.response = {"translation_ko": "셋이서 간다."}

    response = analyze(client, "3人で行く")

    assert response.status_code == 200
    assert response.events == [{"type": "error", "error": "ANALYSIS:FAILED"}]
    assert saved_analyses().count() == 0


def test_llm_error_before_translation_is_an_error_event(client, fake_llm):
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.events == [{"type": "error", "error": "ANALYSIS:FAILED"}]


def test_grammar_that_fails_validation_keeps_the_sent_translation_and_saves_nothing(
    client, fake_llm
):
    # 범위 밖 토큰 ID
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "new_patterns": [new_pattern((0, "lemma"), (9, "lemma"))],
    }

    response = analyze(client, "私は学生です。")

    assert response.events == [
        {
            "type": "translation",
            "translation_ko": "나는 학생입니다.",
            "ruby": response.events[0]["ruby"],
        },
        {"type": "error", "error": "ANALYSIS:FAILED"},
    ]
    assert saved_analyses().count() == 0


def test_reused_analysis_is_sent_at_once(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    analyze(client, "私は学生です。")

    response = post(client, "私は学生です。")

    assert not response.streaming
    assert response["Content-Type"] == "application/x-ndjson"
    events = [json.loads(line) for line in response.content.decode().splitlines()]
    assert [event["type"] for event in events] == ["translation", "analysis"]
    assert events[1]["translation_ko"] == "나는 학생입니다."
    assert len(fake_llm.requests) == 1
