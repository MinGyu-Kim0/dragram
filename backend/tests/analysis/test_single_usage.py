"""승인된 용법 완결 패턴의 단일 후보 구간을 LLM 없이 확정(#39)."""

import pytest

from analysis import review
from analysis.models import GrammarPattern, SentenceAnalysis, SpanMatch
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))
# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"


def register_teiru(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}
    analyze(client, "走っている")
    pattern = GrammarPattern.objects.get()
    pattern.test_cases = [
        {"text": "雨が降っている", "should_match": True},
        {"text": "雨が降る", "should_match": False},
    ]
    pattern.save(update_fields=["test_cases"])
    return pattern


def closed_teiru(client, fake_llm):
    """승인된 용법 하나만 가진, 승인된 용법 완결 ている 패턴."""
    pattern = register_teiru(client, fake_llm)
    review.approve_pattern(pattern)
    review.approve_usage(pattern.usages.get())
    review.close_usages(pattern)
    return pattern


def test_span_of_a_usage_closed_pattern_is_decided_without_asking_the_llm(client, fake_llm):
    closed_teiru(client, fake_llm)
    fake_llm.response = {"translation_ko": "그가 와 있다"}

    response = analyze(client, KITEIRU)

    request = fake_llm.requests[-1]
    assert request["spans"] == []
    assert request["decided_spans"] == [{"start_token_id": 3, "end_token_id": 4, "name": "진행"}]
    # LLM을 부르기 전에 확정 구간을 먼저 보낸다.
    assert response.types() == ["grammar", "translation", "analysis"]
    expected = {
        "start": 3,
        "end": 6,
        "state": "decided",
        "name": "진행",
        "explanation_ko": "동작이 이어지고 있음을 나타낸다",
        "review_status": "approved",
    }
    assert response.events[0]["grammar"] == [expected]
    assert response.json()["grammar"] == [expected]
    span = SentenceAnalysis.objects.latest("id").span_matches.get()
    assert (span.state, span.decided_by) == (SpanMatch.State.DECIDED, "single_usage")


@pytest.mark.parametrize("unready", ["not_closed", "usage_pending"])
def test_span_that_is_not_settled_is_still_asked(client, fake_llm, unready):
    pattern = register_teiru(client, fake_llm)
    review.approve_pattern(pattern)
    if unready == "usage_pending":
        # 용법 완결 표시가 남았더라도 용법이 승인되지 않았으면 확정하지 않는다.
        GrammarPattern.objects.filter(pk=pattern.pk).update(usage_closed=True)
    else:
        review.approve_usage(pattern.usages.get())
    fake_llm.response = {"translation_ko": "그가 와 있다"}

    response = analyze(client, KITEIRU)

    request = fake_llm.requests[-1]
    assert [span["start_token_id"] for span in request["spans"]] == [3]
    assert request["decided_spans"] == []
    assert response.events[0]["grammar"] == []


def test_proposal_at_a_decided_span_is_dropped_without_asking_again(client, fake_llm):
    closed_teiru(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과 상태")],
    }

    analyze(client, KITEIRU)

    assert fake_llm.rejudge_requests == []
    assert GrammarPattern.objects.count() == 1
    assert SentenceAnalysis.objects.latest("id").span_matches.count() == 1


def test_llm_failure_after_the_decided_spans_saves_nothing(client, fake_llm):
    closed_teiru(client, fake_llm)
    before = SentenceAnalysis.objects.count()
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "error"]
    assert SentenceAnalysis.objects.count() == before


def test_candidate_spans_are_sent_as_checking_before_the_translation(client, fake_llm):
    # 미검수 ている(후보 1개)
    register_teiru(client, fake_llm)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "analysis"]
    assert response.events[0] == {
        "type": "grammar",
        "grammar": [],
        # 미검수 패턴·용법이라 미검수로 보인다.
        "checking": [
            {
                "start": 3,
                "end": 6,
                "candidates": [{"name": "진행", "review_status": "pending"}],
            }
        ],
    }


def test_decided_and_checking_spans_are_sent_together(client, fake_llm):
    pattern = closed_teiru(client, fake_llm)
    # 토큰: 0 歩き / 1 ながら. 미검수 ながら(후보 1개)
    fake_llm.response = {
        "translation_ko": "걸으면서",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                pattern_name="ながら",
                usage_name="동시 동작",
                example_ja="音楽を聞きながら歩く",
            )
        ],
    }
    analyze(client, "歩きながら")
    assert GrammarPattern.objects.exclude(pk=pattern.pk).count() == 1
    # 후보 ID는 패턴 등록 순서로 매긴다(ている 1, ながら 2).
    fake_llm.response = {
        "translation_ko": "걸으면서 와 있다",
        "spans": [span_answer(0, "usage", 2)],
    }

    # 토큰: 0 歩き / 1 ながら / 2 来 / 3 て / 4 いる
    response = analyze(client, "歩きながら来ている")

    assert response.types() == ["grammar", "translation", "analysis"]
    first = response.events[0]
    assert [item["name"] for item in first["grammar"]] == ["진행"]
    assert first["checking"] == [
        {
            "start": 2,
            "end": 5,
            "candidates": [{"name": "동시 동작", "review_status": "pending"}],
        }
    ]


def test_sentence_without_matched_spans_starts_with_the_translation(client, fake_llm):
    fake_llm.response = {"translation_ko": "비가 온다"}

    response = analyze(client, "雨が降る")

    assert response.types() == ["translation", "analysis"]


def test_only_decided_spans_leave_checking_empty(client, fake_llm):
    closed_teiru(client, fake_llm)
    fake_llm.response = {"translation_ko": "그가 와 있다"}

    response = analyze(client, KITEIRU)

    assert response.events[0]["checking"] == []


def test_checking_candidate_of_an_approved_usage_and_pattern_is_approved(client, fake_llm):
    # 승인됐지만 용법 완결은 아닌 ている
    pattern = register_teiru(client, fake_llm)
    review.approve_pattern(pattern)
    review.approve_usage(pattern.usages.get())
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, KITEIRU)

    [item] = response.events[0]["checking"]
    assert item["candidates"] == [{"name": "진행", "review_status": "approved"}]
