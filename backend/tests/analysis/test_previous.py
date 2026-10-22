"""stale 분석의 옛 결과를 먼저 보내기(재분석 중, #60)."""

import json

import pytest

from analysis import review
from analysis.models import GrammarPattern, SentenceAnalysis
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, post, span_answer, word_item

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))
HASHIRU = word_item(token_id=0, lemma="走る", reading="はしる", meaning_ko="달리다")


def stale_teiru(client, fake_llm):
    """ている를 등록한 走っている 분석을 만들고 stale로 만든다."""
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [TEIRU],
        "words": [HASHIRU],
    }
    analyze(client, "走っている")
    SentenceAnalysis.objects.update(is_stale=True)
    fake_llm.response = {"translation_ko": "달리는 중이다", "spans": [span_answer(0, "usage", 1)]}
    return SentenceAnalysis.objects.get()


def first_event(response):
    return json.loads(next(iter(response.streaming_content)))


def test_stale_analysis_sends_its_previous_result_before_calling_the_llm(client, fake_llm):
    stale_teiru(client, fake_llm)
    calls = len(fake_llm.requests)

    response = post(client, "走っている")

    first = first_event(response)
    assert len(fake_llm.requests) == calls
    assert first["type"] == "previous"
    assert first["translation_ko"] == "달리고 있다"
    assert first["ruby"] == [{"start": 0, "end": 1, "reading": "はし"}]
    # 미검수 패턴·용법으로 정한 구간은 미검수로 실린다.
    assert first["grammar"] == [
        {
            "start": 2,
            "end": 5,
            "state": "decided",
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "review_status": "pending",
        }
    ]
    assert [(w["lemma"], w["meaning_ko"]) for w in first["words"]] == [("走る", "달리다")]


def test_reanalysis_after_the_previous_result_makes_the_same_llm_calls(client, fake_llm):
    stale_teiru(client, fake_llm)
    calls = len(fake_llm.requests)

    response = analyze(client, "走っている")

    assert response.types()[0] == "previous"
    assert response.types()[-1] == "analysis"
    assert response.events[-1]["translation_ko"] == "달리는 중이다"
    assert len(fake_llm.requests) == calls + 1


def test_previous_result_leaves_out_spans_of_a_rejected_usage(client, fake_llm):
    stale_teiru(client, fake_llm)
    SentenceAnalysis.objects.update(is_stale=False)
    review.reject_usage(GrammarPattern.objects.get().usages.get())
    # 진행 용법이 반려돼 ている 패턴에는 후보가 없다.
    fake_llm.response = {"translation_ko": "달리는 중이다"}

    response = analyze(client, "走っている")

    assert response.events[0]["type"] == "previous"
    assert response.events[0]["grammar"] == []
    assert response.types()[-1] == "analysis"


def test_previous_result_leaves_out_spans_of_a_rejected_pattern(client, fake_llm):
    stale_teiru(client, fake_llm)
    SentenceAnalysis.objects.update(is_stale=False)
    review.reject_pattern(GrammarPattern.objects.get())
    # 반려된 패턴은 매칭되지 않는다.
    fake_llm.response = {"translation_ko": "달리는 중이다"}

    response = analyze(client, "走っている")

    assert response.events[0]["type"] == "previous"
    assert response.events[0]["grammar"] == []
    assert response.types()[-1] == "analysis"


def test_llm_failure_after_the_previous_result_is_an_error_event_and_keeps_it_stale(
    client, fake_llm
):
    analysis = stale_teiru(client, fake_llm)
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, "走っている")

    assert response.status_code == 200
    assert response.types() == ["previous", "grammar", "error"]
    analysis.refresh_from_db()
    assert (analysis.translation_ko, analysis.is_stale) == ("달리고 있다", True)


def test_row_without_a_previous_result_is_analyzed_as_new(client, fake_llm):
    stale_teiru(client, fake_llm)
    SentenceAnalysis.objects.update(draft_analysis=None)

    response = analyze(client, "走っている")

    assert "previous" not in response.types()
