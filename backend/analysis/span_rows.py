"""구간 매칭 행 만들기와 저장 검사. 작업자와 재매칭이 함께 쓴다."""

from analysis.models import (
    GrammarPattern,
    ReviewStatus,
    SpanMatch,
    UsageRule,
)
from analysis.sentence import _pattern_statuses


def _usage_owner(pattern):
    """그 패턴의 구간에 새 용법을 더할 패턴. 연결된 회화체면 원형이다(#63)."""
    return pattern.variant_of or pattern


def _basis_changed(rows, rules):
    """판정 근거로 읽은 상태가 저장 직전에 바뀌어 이 구간들을 저장하면 안 되는가(#63).

    넷을 본다. 원형 연결이 분석할 때와 다른 구간이 있거나(_links_changed), LLM 없이 확정한
    구간의 용법 완결이 풀렸거나(이번 저장이 같은 원형에 새 용법을 더해 풀었을 수 있다), 판별
    규칙으로 확정한 근거(규칙·패턴·용법의 승인)가 무너졌거나, 분석할 때 읽은 승인된 판별
    규칙(rules, _approved_rules)에 없던 규칙이 그 구간들의 패턴에 승인됐다. 그대로
    저장하면 그 stale 처리가 이 트랜잭션의 구간을 보지 못해 다시 분석될 계기가 없다.
    """
    closed = {row.pattern_id for row in rows if row.decided_by == SpanMatch.DecidedBy.SINGLE_USAGE}
    opened = GrammarPattern.objects.filter(pk__in=closed, usage_closed=False).exists()
    # 판별 규칙으로 확정한 구간의 규칙·패턴(원형 포함)·용법이 그사이 승인 상태가 아니게 됐다(#55).
    ruled = UsageRule.objects.filter(
        pk__in={row.rule_id for row in rows if row.rule_id is not None}
    ).select_related("usage", "pattern__variant_of")
    unusable = any(
        rule.status != UsageRule.Status.APPROVED
        or rule.usage.status != ReviewStatus.APPROVED
        or _pattern_statuses(rule.pattern) != {ReviewStatus.APPROVED}
        for rule in ruled
    )
    read = {rule.pk for pattern_rules in rules.values() for rule in pattern_rules}
    approved = (
        UsageRule.objects.filter(
            status=UsageRule.Status.APPROVED,
            pattern__in={row.pattern_id for row in rows if row.pattern_id},
        )
        .exclude(pk__in=read)
        .exists()
    )
    return opened or unusable or approved or _links_changed(rows)


def _links_changed(rows):
    """구간마다 분석할 때 읽은 원형 연결이 지금과 다른가(#63). 판정 상태와 상관없이 모두 본다.

    분석하는 사이 연결·해제가 일어나면 후보·용법이 바뀐 패턴 기준이 된다. 그대로 저장하면 연결·
    해제의 stale 처리가 저장 전에 지나가 다시 분석될 계기가 없어서 저장하지 않는다. 저장하는
    트랜잭션은 맨 처음 patterns.lock_links()로 연결·해제와 직렬화하므로, 여기서 읽은 연결은
    커밋할 때까지 바뀌지 않는다.
    """
    read = [(row.pattern_id, row.pattern.variant_of_id) for row in rows if row.pattern_id]
    current = dict(
        GrammarPattern.objects.filter(pk__in={pk for pk, _ in read}).values_list(
            "pk", "variant_of_id"
        )
    )
    return any(current.get(pk) != base for pk, base in read)


def _stored_keys(analysis):
    """저장된 구간의 열쇠 (패턴 ID, 키 텍스트 start, end)들. 패턴이 있는 모든 상태를 센다(#41)."""
    return set(
        analysis.span_matches.filter(pattern__isnull=False).values_list(
            "pattern_id", "start_offset", "end_offset"
        )
    )


def _is_place_conflict(error):
    """같은 자리의 같은 패턴 구간을 두 번 넣어 구간 유일성 제약에 걸렸는가(#41)."""
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == "span_match_place_unique"


class _PatternTaken(Exception):  # noqa: N818
    """새 패턴을 등록하는 사이 다른 요청이 같은 조건의 패턴을 먼저 등록했다."""
