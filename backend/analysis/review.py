"""패턴·용법의 승인·반려와 그에 따른 상태 전이(#38).

admin 액션과 이후 티켓이 함께 쓴다. 함수마다 한 트랜잭션에서 조건을 검사하고 상태를 바꾼다.
조건을 어기면 바꾸지 않고 Refused를 던진다.
"""

from django.db import transaction
from django.db.models import F

from analysis import patterns
from analysis.models import GrammarPattern, ReviewStatus, SentenceAnalysis
from analysis.morphology import morphemes
from analysis.normalize import analysis_text


class Refused(Exception):  # noqa: N818
    """조건을 어겨 상태를 바꾸지 않았다. 메시지는 관리자에게 보이는 이유다."""


def _matches(conditions, text):
    analysis, _ = analysis_text(text)
    return bool(analysis) and bool(patterns.match_starts(conditions, morphemes(analysis)))


def test_cases_failure(pattern):
    """test_cases가 통과하지 못하는 이유. 통과하면 None.

    '걸려야 함'·'걸리면 안 됨' 예문이 각각 하나 이상 있고, 모두 매칭기 결과가 기대와 같아야
    한다. 빈 배열은 통과가 아니다.
    """
    cases = pattern.test_cases
    if not any(case["should_match"] for case in cases):
        return "'걸려야 함' 예문이 없습니다"
    if all(case["should_match"] for case in cases):
        return "'걸리면 안 됨' 예문이 없습니다"
    conditions = patterns.conditions_of(pattern)
    for case in cases:
        if _matches(conditions, case["text"]) != case["should_match"]:
            expected = "걸려야" if case["should_match"] else "걸리면 안 되"
            return f"{expected} 하는 예문이 기대와 다릅니다: {case['text']}"
    return None


def _locked(pattern):
    return GrammarPattern.objects.select_for_update().get(pk=pattern.pk)


def _require(obj, *statuses):
    if obj.status not in statuses:
        raise Refused(f"지금 상태({obj.get_status_display()})에서는 할 수 없습니다")


@transaction.atomic
def approve_pattern(pattern):
    """test_cases를 통과한 미검수 패턴을 승인한다."""
    pattern = _locked(pattern)
    _require(pattern, ReviewStatus.PENDING)
    failure = test_cases_failure(pattern)
    if failure:
        raise Refused(failure)
    pattern.status = ReviewStatus.APPROVED
    pattern.save(update_fields=["status"])


def _make_stale(**span_filter):
    """구간이 span_filter에 걸리는 분석을 stale로 만들고 세대 번호를 올린다."""
    SentenceAnalysis.objects.filter(
        id__in=SentenceAnalysis.objects.filter(
            **{f"span_matches__{key}": value for key, value in span_filter.items()}
        ).values("id")
    ).update(is_stale=True, generation=F("generation") + 1)


def _set_active(pattern, active):
    """is_active를 바꾼다. 실제로 바뀌면 같은 트랜잭션에서 패턴 세트 버전을 올린다."""
    if pattern.is_active == active:
        return
    pattern.is_active = active
    pattern.save(update_fields=["is_active"])
    patterns.raise_pattern_set_version()


@transaction.atomic
def reject_pattern(pattern):
    """패턴을 반려해 매칭에서 빼고, 그 패턴으로 매칭된 구간이 있는 분석을 stale로 만든다."""
    pattern = _locked(pattern)
    _require(pattern, ReviewStatus.PENDING, ReviewStatus.APPROVED)
    pattern.status = ReviewStatus.REJECTED
    pattern.usage_closed = False
    pattern.save(update_fields=["status", "usage_closed"])
    _set_active(pattern, False)
    _make_stale(pattern=pattern)


def _has_activation_basis(pattern):
    """활성화 근거: test_cases에 매칭기를 통과하는 '걸려야 함' 예문이 하나 이상 있다."""
    conditions = patterns.conditions_of(pattern)
    return any(
        case["should_match"] and _matches(conditions, case["text"]) for case in pattern.test_cases
    )


@transaction.atomic
def unreject_pattern(pattern):
    """반려를 취소해 미검수로 되돌린다. 활성화 근거가 있으면 다시 매칭에 쓴다."""
    pattern = _locked(pattern)
    _require(pattern, ReviewStatus.REJECTED)
    pattern.status = ReviewStatus.PENDING
    pattern.save(update_fields=["status"])
    _set_active(pattern, _has_activation_basis(pattern))
    _make_stale(pattern=pattern)


@transaction.atomic
def unapprove_pattern(pattern):
    """승인을 취소해 미검수로 되돌린다. 용법 완결도 뗀다."""
    pattern = _locked(pattern)
    _require(pattern, ReviewStatus.APPROVED)
    pattern.status = ReviewStatus.PENDING
    pattern.usage_closed = False
    pattern.save(update_fields=["status", "usage_closed"])
    _make_stale(pattern=pattern)
