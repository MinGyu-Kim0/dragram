"""분석 API: 결과를 나오는 대로 보내기(줄 단위 JSON 스트림)."""

import json

import pytest

from analysis.models import SentenceAnalysis
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, post

pytestmark = pytest.mark.django_db


def test_translation_is_sent_before_grammar_and_words(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "먹는다",
        "new_patterns": [
            new_pattern(
                (0, "lemma"), pattern_name="食べる", usage_name="문법", example_ja="パンを食べる"
            )
        ],
    }

    response = post(client, "食べる")

    assert response["Content-Type"] == "application/x-ndjson"
    lines = iter(response.streaming_content)
    first = json.loads(next(lines))
    # LLM이 응답 전체를 다 주기 전에 번역(과 루비)이 나간다.
    assert fake_llm.result_given is False
    assert first == {
        "type": "translation",
        "translation_ko": "먹는다",
        "ruby": [{"start": 0, "end": 1, "reading": "た"}],
    }
    second = json.loads(next(lines))
    assert second["type"] == "analysis"
    assert second["translation_ko"] == "먹는다"
    assert [item["name"] for item in second["grammar"]] == ["문법"]
    assert second["words"] == []
    assert list(lines) == []


def test_failure_before_translation_keeps_the_error_status(client, fake_llm):
    # 응답을 시작하기 전이라 다른 API 오류처럼 상태 코드로 알린다.
    # 숫자 자리표시자가 빠진 번역
    fake_llm.response = {"translation_ko": "셋이서 간다."}

    response = analyze(client, "3人で行く")

    assert response.status_code == 502
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


def test_llm_error_before_translation_keeps_the_error_status(client, fake_llm):
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert response.json() == {"error": "ANALYSIS:FAILED"}


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
    assert SentenceAnalysis.objects.count() == 0


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
