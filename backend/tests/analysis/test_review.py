"""패턴·용법 승인과 반려(#38)."""

import pytest

from analysis import review
from analysis.models import GrammarPattern, PatternSetVersion, ReviewStatus, SentenceAnalysis
from tests.analysis.helpers import analyze, new_pattern

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
