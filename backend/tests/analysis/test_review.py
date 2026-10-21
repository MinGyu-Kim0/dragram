"""패턴·용법 승인과 반려(#38)."""

import threading

import pytest
from django.db import connection, transaction

from analysis import patterns, review
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternSetVersion,
    ReviewStatus,
    SentenceAnalysis,
)
from tests.analysis.helpers import analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))


def register_teiru(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}
    analyze(client, "走っている")
    return GrammarPattern.objects.get()


def with_cases(pattern, *cases):
    pattern.test_cases = [{"text": text, "should_match": match} for text, match in cases]
    pattern.save(update_fields=["test_cases"])
    return pattern


@pytest.mark.parametrize(
    "cases",
    [
        [],
        # '걸리면 안 됨' 예문이 없다
        [("雨が降っている", True)],
        # '걸려야 함' 예문이 없다
        [("雨が降る", False)],
        # 걸려야 하는데 안 걸린다
        [("雨が降る", True), ("風が吹く", False)],
        # 걸리면 안 되는데 걸린다
        [("雨が降っている", True), ("風が吹いている", False)],
    ],
)
def test_pattern_whose_test_cases_do_not_pass_cannot_be_approved(client, fake_llm, cases):
    pattern = with_cases(register_teiru(client, fake_llm), *cases)

    with pytest.raises(review.Refused):
        review.approve_pattern(pattern)

    pattern.refresh_from_db()
    assert pattern.status == ReviewStatus.PENDING


def test_pattern_whose_test_cases_pass_is_approved(client, fake_llm):
    pattern = with_cases(
        register_teiru(client, fake_llm), ("雨が降っている", True), ("雨が降る", False)
    )

    review.approve_pattern(pattern)

    pattern.refresh_from_db()
    assert pattern.status == ReviewStatus.APPROVED


def version():
    return PatternSetVersion.objects.get().version


def analysis_of(client, text, fake_llm, **response):
    fake_llm.response = {"translation_ko": "번역", **response}
    analyze(client, text)
    return SentenceAnalysis.objects.latest("id")


def test_rejected_pattern_stops_matching_and_makes_its_analyses_stale(client, fake_llm):
    pattern = register_teiru(client, fake_llm)
    using = SentenceAnalysis.objects.get()
    other = analysis_of(client, "雨が降る", fake_llm)
    before = version()

    review.reject_pattern(pattern)

    pattern.refresh_from_db()
    assert (pattern.status, pattern.is_active) == (ReviewStatus.REJECTED, False)
    assert version() == before + 1
    using.refresh_from_db()
    other.refresh_from_db()
    assert (using.is_stale, using.generation) == (True, 1)
    assert (other.is_stale, other.generation) == (False, 0)


def test_rejecting_an_inactive_pattern_keeps_the_pattern_set_version(client, fake_llm):
    # 예문이 패턴에 걸리지 않아 비활성으로 등록된다.
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [{**TEIRU, "example_ja": "雨が降る"}],
    }
    analyze(client, "走っている")
    pattern = GrammarPattern.objects.get()
    before = version()

    review.reject_pattern(pattern)

    assert version() == before


def test_unrejected_pattern_with_a_passing_example_goes_back_to_pending_and_active(
    client, fake_llm
):
    pattern = register_teiru(client, fake_llm)
    review.reject_pattern(pattern)
    using = SentenceAnalysis.objects.get()
    before = version()

    review.unreject_pattern(pattern)

    pattern.refresh_from_db()
    assert (pattern.status, pattern.is_active) == (ReviewStatus.PENDING, True)
    assert version() == before + 1
    using.refresh_from_db()
    assert (using.is_stale, using.generation) == (True, 2)


def test_unrejected_pattern_without_a_passing_example_stays_inactive(client, fake_llm):
    pattern = register_teiru(client, fake_llm)
    review.reject_pattern(pattern)
    with_cases(pattern, ("雨が降る", True))
    before = version()

    review.unreject_pattern(pattern)

    pattern.refresh_from_db()
    assert (pattern.status, pattern.is_active) == (ReviewStatus.PENDING, False)
    assert version() == before


def test_unapproved_pattern_goes_back_to_pending_and_makes_its_analyses_stale(client, fake_llm):
    pattern = with_cases(
        register_teiru(client, fake_llm), ("雨が降っている", True), ("雨が降る", False)
    )
    review.approve_pattern(pattern)
    using = SentenceAnalysis.objects.get()
    before = version()

    review.unapprove_pattern(pattern)

    pattern.refresh_from_db()
    assert (pattern.status, pattern.is_active) == (ReviewStatus.PENDING, True)
    assert version() == before
    using.refresh_from_db()
    assert (using.is_stale, using.generation) == (True, 1)


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (ReviewStatus.REJECTED, review.approve_pattern),
        (ReviewStatus.APPROVED, review.approve_pattern),
        (ReviewStatus.REJECTED, review.reject_pattern),
        (ReviewStatus.PENDING, review.unreject_pattern),
        (ReviewStatus.APPROVED, review.unreject_pattern),
        (ReviewStatus.PENDING, review.unapprove_pattern),
        (ReviewStatus.REJECTED, review.unapprove_pattern),
    ],
)
def test_pattern_action_from_a_wrong_status_is_refused(client, fake_llm, status, action):
    pattern = with_cases(
        register_teiru(client, fake_llm), ("雨が降っている", True), ("雨が降る", False)
    )
    GrammarPattern.objects.filter(pk=pattern.pk).update(status=status)

    with pytest.raises(review.Refused):
        action(pattern)

    pattern.refresh_from_db()
    assert pattern.status == status


def teiru_with_candidate_only_analysis(client, fake_llm):
    """ている를 등록하고, 진행 용법이 후보로만 들어간(해당 없음) 분석을 하나 더 만든다."""
    pattern = register_teiru(client, fake_llm)
    decided = SentenceAnalysis.objects.get()
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    candidate_only = analysis_of(
        client, "彼が来ている", fake_llm, spans=[span_answer(0, "not_applicable")]
    )
    return pattern, pattern.usages.get(), decided, candidate_only


def stale(*analyses):
    for analysis in analyses:
        analysis.refresh_from_db()
    return [analysis.is_stale for analysis in analyses]


def test_rejected_usage_makes_only_analyses_decided_by_it_stale(client, fake_llm):
    pattern, usage, decided, candidate_only = teiru_with_candidate_only_analysis(client, fake_llm)

    review.reject_usage(usage)

    usage.refresh_from_db()
    assert usage.status == ReviewStatus.REJECTED
    assert stale(decided, candidate_only) == [True, False]


def test_unrejected_usage_makes_every_analysis_of_its_pattern_stale(client, fake_llm):
    pattern, usage, decided, candidate_only = teiru_with_candidate_only_analysis(client, fake_llm)
    review.reject_usage(usage)

    review.unreject_usage(usage)

    usage.refresh_from_db()
    assert usage.status == ReviewStatus.PENDING
    assert stale(decided, candidate_only) == [True, True]


def test_usage_approval_and_its_cancellation(client, fake_llm):
    pattern, usage, decided, candidate_only = teiru_with_candidate_only_analysis(client, fake_llm)

    review.approve_usage(usage)
    usage.refresh_from_db()
    assert usage.status == ReviewStatus.APPROVED
    assert stale(decided, candidate_only) == [False, False]

    review.unapprove_usage(usage)
    usage.refresh_from_db()
    assert usage.status == ReviewStatus.PENDING
    assert stale(decided, candidate_only) == [True, False]


def test_usage_of_a_rejected_pattern_cannot_be_approved(client, fake_llm):
    pattern = register_teiru(client, fake_llm)
    review.reject_pattern(pattern)
    usage = pattern.usages.get()

    with pytest.raises(review.Refused):
        review.approve_usage(usage)

    usage.refresh_from_db()
    assert usage.status == ReviewStatus.PENDING


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (ReviewStatus.APPROVED, review.approve_usage),
        (ReviewStatus.REJECTED, review.approve_usage),
        (ReviewStatus.REJECTED, review.reject_usage),
        (ReviewStatus.PENDING, review.unreject_usage),
        (ReviewStatus.PENDING, review.unapprove_usage),
    ],
)
def test_usage_action_from_a_wrong_status_is_refused(client, fake_llm, status, action):
    usage = register_teiru(client, fake_llm).usages.get()
    GrammarUsage.objects.filter(pk=usage.pk).update(status=status)

    with pytest.raises(review.Refused):
        action(usage)

    usage.refresh_from_db()
    assert usage.status == status


def approved_teiru(client, fake_llm):
    pattern = with_cases(
        register_teiru(client, fake_llm), ("雨が降っている", True), ("雨が降る", False)
    )
    review.approve_pattern(pattern)
    usage = pattern.usages.get()
    review.approve_usage(usage)
    pattern.refresh_from_db()
    return pattern, usage


def closed(pattern):
    pattern.refresh_from_db()
    return pattern.usage_closed


def test_pattern_with_one_approved_usage_is_marked_usage_closed(client, fake_llm):
    pattern, _ = approved_teiru(client, fake_llm)
    using = SentenceAnalysis.objects.get()

    review.close_usages(pattern)

    assert closed(pattern)
    assert stale(using) == [True]


def test_usage_closed_mark_is_removed_and_its_analyses_become_stale(client, fake_llm):
    pattern, _ = approved_teiru(client, fake_llm)
    review.close_usages(pattern)
    using = SentenceAnalysis.objects.get()
    SentenceAnalysis.objects.update(is_stale=False)

    review.open_usages(pattern)

    assert not closed(pattern)
    assert stale(using) == [True]


@pytest.mark.parametrize(
    "unready",
    [
        # 패턴이 승인되지 않았다
        lambda pattern, usage: review.unapprove_pattern(pattern),
        # 용법이 승인되지 않았다
        lambda pattern, usage: review.unapprove_usage(usage),
        # test_cases가 통과하지 않는다
        lambda pattern, usage: with_cases(pattern, ("雨が降っている", True)),
        # 반려되지 않은 용법이 둘이다
        lambda pattern, usage: patterns.add_usage(pattern, "결과 상태", "결과가 남아 있다", None),
    ],
)
def test_usage_closed_needs_an_approved_pattern_and_exactly_one_approved_usage(
    client, fake_llm, unready
):
    pattern, usage = approved_teiru(client, fake_llm)
    unready(pattern, usage)

    with pytest.raises(review.Refused):
        review.close_usages(pattern)

    assert not closed(pattern)


def test_rejected_second_usage_does_not_count_for_usage_closed(client, fake_llm):
    pattern, _ = approved_teiru(client, fake_llm)
    review.reject_usage(patterns.add_usage(pattern, "결과 상태", "결과가 남아 있다", None))

    review.close_usages(pattern)

    assert closed(pattern)


def unreject_second_usage(pattern):
    """반려된 둘째 용법을 되살려 반려되지 않은 용법을 둘로 만든다."""
    second = GrammarUsage.objects.get(pattern=pattern, name="결과 상태")
    review.unreject_usage(second)


@pytest.mark.parametrize(
    "event",
    [
        lambda pattern, usage: patterns.add_usage(pattern, "계속", "상태가 이어진다", None),
        lambda pattern, usage: unreject_second_usage(pattern),
        lambda pattern, usage: review.unapprove_usage(usage),
        lambda pattern, usage: review.reject_usage(usage),
        lambda pattern, usage: review.unapprove_pattern(pattern),
        lambda pattern, usage: review.reject_pattern(pattern),
    ],
)
def test_usage_closed_is_removed_automatically(client, fake_llm, event):
    pattern, usage = approved_teiru(client, fake_llm)
    review.reject_usage(patterns.add_usage(pattern, "결과 상태", "결과가 남아 있다", None))
    review.close_usages(pattern)
    using = SentenceAnalysis.objects.get()
    SentenceAnalysis.objects.update(is_stale=False)

    event(pattern, usage)

    assert not closed(pattern)
    assert stale(using) == [True]


def test_stale_analysis_is_analyzed_again_and_replaced(client, fake_llm):
    pattern, usage, decided, _ = teiru_with_candidate_only_analysis(client, fake_llm)
    review.reject_usage(usage)
    calls = len(fake_llm.requests)
    # 진행 용법이 반려돼 ている 패턴에는 후보가 없다.
    fake_llm.response = {"translation_ko": "달리는 중이다"}

    response = analyze(client, "走っている")

    assert len(fake_llm.requests) == calls + 1
    assert fake_llm.requests[-1]["spans"] == []
    assert response.json()["translation_ko"] == "달리는 중이다"
    decided.refresh_from_db()
    assert (decided.translation_ko, decided.is_stale) == ("달리는 중이다", False)
    # 반려된 용법으로 정했던 옛 구간은 남지 않는다.
    assert not decided.span_matches.exists()


def test_analysis_outdated_while_being_analyzed_is_sent_but_not_saved(client, fake_llm):
    pattern, usage, decided, _ = teiru_with_candidate_only_analysis(client, fake_llm)
    review.reject_usage(usage)
    fake_llm.response = {"translation_ko": "달리는 중이다"}
    # 분석하는 사이 영향 범위의 용법 상태가 또 바뀐다.
    fake_llm.before_respond = lambda: review.unreject_usage(usage)

    response = analyze(client, "走っている")

    assert response.json()["translation_ko"] == "달리는 중이다"
    decided.refresh_from_db()
    assert (decided.translation_ko, decided.is_stale) == ("달리고 있다", True)


def test_fresh_analysis_is_still_reused_without_llm(client, fake_llm):
    register_teiru(client, fake_llm)
    calls = len(fake_llm.requests)

    analyze(client, "走っている")

    assert len(fake_llm.requests) == calls


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_usage_closed_waits_for_a_usage_being_added(client, fake_llm):
    pattern, _ = approved_teiru(client, fake_llm)
    added, release = threading.Event(), threading.Event()
    result = {}

    def analysis_adds_a_usage():
        # 분석 트랜잭션이 새 용법을 넣고 아직 커밋하지 않았다.
        with transaction.atomic():
            patterns.add_usage(pattern, "결과 상태", "결과가 남아 있다", None)
            added.set()
            release.wait(5)
        connection.close()

    def admin_closes_usages():
        try:
            review.close_usages(pattern)
        except review.Refused:
            result["refused"] = True
        connection.close()

    analysis = threading.Thread(target=analysis_adds_a_usage)
    analysis.start()
    added.wait(5)
    admin = threading.Thread(target=admin_closes_usages)
    admin.start()
    # 관리자 쪽이 패턴 잠금을 기다리게 한 뒤 분석을 커밋한다.
    admin.join(0.5)
    release.set()
    analysis.join()
    admin.join()

    assert result == {"refused": True}
    assert not closed(pattern)
