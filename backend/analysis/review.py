"""패턴·용법의 승인·반려와 그에 따른 상태 전이(#38).

admin 액션과 이후 티켓이 함께 쓴다. 함수마다 한 트랜잭션에서 조건을 검사하고 상태를 바꾼다.
조건을 어기면 바꾸지 않고 Refused를 던진다.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from analysis import patterns
from analysis.models import GrammarPattern, GrammarUsage, ReviewStatus, UsageRule
from analysis.morphology import morphemes
from analysis.normalize import analysis_text
from analysis.rules import condition_matches


class Refused(Exception):  # noqa: N818
    """조건을 어겨 상태를 바꾸지 않았다. 메시지는 관리자에게 보이는 이유다."""


def matches(conditions, text):
    """매칭기로 예문에 패턴이 걸리는지 본다."""
    analysis, _ = analysis_text(text)
    return bool(analysis) and bool(patterns.match_starts(conditions, morphemes(analysis)))


def test_cases_failure(pattern, cases=None):
    """test_cases(주지 않으면 패턴에 저장된 것)가 통과하지 못하는 이유. 통과하면 None.

    '걸려야 함'·'걸리면 안 됨' 예문이 각각 하나 이상 있고, 모두 매칭기 결과가 기대와 같아야
    한다. 빈 배열은 통과가 아니다.
    """
    cases = pattern.test_cases if cases is None else cases
    if not any(case["should_match"] for case in cases):
        return "'걸려야 함' 예문이 없습니다"
    if all(case["should_match"] for case in cases):
        return "'걸리면 안 됨' 예문이 없습니다"
    conditions = patterns.conditions_of(pattern)
    for case in cases:
        if matches(conditions, case["text"]) != case["should_match"]:
            expected = "걸려야" if case["should_match"] else "걸리면 안 되"
            return f"{expected} 하는 예문이 기대와 다릅니다: {case['text']}"
    return None


def _locked(pattern):
    # 잠금은 모두 FOR NO KEY UPDATE다. 서로는 막아 직렬화하지만, 구간(span_match)의 FK가
    # 커밋 때 거는 KEY SHARE는 막지 않아 분석 저장과 교착하지 않는다. 원형 쪽 사건이 연결된
    # 회화체도 바꾸므로 그 회화체들까지 id 순서로 함께 잠근다(#63).
    return patterns.lock_families(pattern)[pattern.pk]


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


def _set_active(pattern, active):
    """is_active를 바꾼다. 실제로 바뀌면 같은 트랜잭션에서 패턴 세트 버전을 올리고 True다."""
    if pattern.is_active == active:
        return False
    pattern.is_active = active
    pattern.save(update_fields=["is_active"])
    patterns.raise_pattern_set_version()
    return True


def _locked_with_base(pattern):
    """패턴과, 연결됐으면 그 원형을 함께 잠근다. (패턴, 원형 또는 None)이다."""
    base_id = GrammarPattern.objects.values_list("variant_of_id", flat=True).get(pk=pattern.pk)
    family = [pattern] + ([GrammarPattern(pk=base_id)] if base_id else [])
    locked = patterns.lock_families(*family)
    pattern = locked[pattern.pk]
    if pattern.variant_of_id != base_id:
        raise Refused("그사이 원형 연결 상태가 바뀌었습니다")
    return pattern, locked.get(base_id)


@transaction.atomic
def reject_pattern(pattern):
    """패턴을 반려해 매칭에서 빼고, 그 패턴으로 매칭된 구간이 있는 분석을 stale로 만든다."""
    pattern = _locked(pattern)
    _require(pattern, ReviewStatus.PENDING, ReviewStatus.APPROVED)
    pattern.status = ReviewStatus.REJECTED
    pattern.save(update_fields=["status"])
    _set_active(pattern, False)
    patterns.clear_usage_closed(pattern)
    patterns.make_stale(pattern=pattern)


def _has_activation_basis(pattern):
    """활성화 근거: test_cases에 매칭기를 통과하는 '걸려야 함' 예문이 하나 이상 있다."""
    conditions = patterns.conditions_of(pattern)
    return any(
        case["should_match"] and matches(conditions, case["text"]) for case in pattern.test_cases
    )


@transaction.atomic
def unreject_pattern(pattern):
    """반려를 취소해 미검수로 되돌린다. 활성화 근거가 있으면 다시 매칭에 쓴다."""
    pattern = _locked(pattern)
    _require(pattern, ReviewStatus.REJECTED)
    was_matchable = patterns.matchable_family(pattern)
    pattern.status = ReviewStatus.PENDING
    pattern.save(update_fields=["status"])
    activated = _set_active(pattern, _has_activation_basis(pattern))
    # 원형이 비활성으로 남아도 연결된 회화체는 원형의 용법으로 매칭 자격을 되찾을 수 있다(#63).
    if not activated and patterns.matchable_family(pattern) - was_matchable:
        patterns.raise_pattern_set_version()
    patterns.make_stale(pattern=pattern)


@transaction.atomic
def unapprove_pattern(pattern):
    """승인을 취소해 미검수로 되돌린다. 용법 완결도 뗀다."""
    pattern = _locked(pattern)
    _require(pattern, ReviewStatus.APPROVED)
    pattern.status = ReviewStatus.PENDING
    pattern.save(update_fields=["status"])
    patterns.clear_usage_closed(pattern)
    patterns.make_stale(pattern=pattern)


def _locked_usage(usage):
    """용법과 그 소속 패턴을 잠근다. 패턴을 먼저 잠가 패턴 쪽 전이와 순서를 맞춘다.

    용법을 읽어 둔 뒤 그 용법이 원형 용법으로 합쳐져 지워졌거나 원형 아래로 옮겨졌으면, 읽어 둔
    소속에서 고른 상태 변경이라 거부한다(#64).
    """
    moved = Refused("그사이 용법이 원형 용법으로 합쳐지거나 원형 아래로 옮겨졌습니다")
    pattern_id = usage.pattern_id
    pattern = _locked(GrammarPattern(pk=pattern_id))
    usage = GrammarUsage.objects.select_for_update(no_key=True).filter(pk=usage.pk).first()
    if usage is None or usage.pattern_id != pattern_id:
        raise moved
    return pattern, usage


@transaction.atomic
def close_usages(pattern):
    """용법 완결을 표시한다. 패턴이 승인됐고 test_cases를 통과하며, 반려되지 않은 용법이
    정확히 하나이고 그 용법이 승인됐을 때만 한다. 연결된 회화체는 원형도 승인돼야 하고, 용법은
    원형의 것을 본다(#63)."""
    pattern, base = _locked_with_base(pattern)
    if pattern.status != ReviewStatus.APPROVED:
        raise Refused("승인된 패턴만 용법 완결로 표시할 수 있습니다")
    if base is not None and base.status != ReviewStatus.APPROVED:
        raise Refused("원형 패턴이 승인돼야 합니다")
    failure = test_cases_failure(pattern)
    if failure:
        raise Refused(failure)
    usages = list(
        GrammarUsage.objects.select_for_update(no_key=True)
        .filter(pattern=base or pattern)
        .exclude(status=ReviewStatus.REJECTED)
    )
    if len(usages) != 1:
        raise Refused("반려되지 않은 용법이 정확히 하나여야 합니다")
    if usages[0].status != ReviewStatus.APPROVED:
        raise Refused("그 용법이 승인돼야 합니다")
    if pattern.usage_closed:
        return
    pattern.usage_closed = True
    pattern.save(update_fields=["usage_closed"])
    patterns.make_stale(pattern=pattern)


@transaction.atomic
def open_usages(pattern):
    """용법 완결 표시를 뗀다."""
    patterns.clear_usage_closed(_locked(pattern))


@transaction.atomic
def approve_usage(usage):
    """미검수 용법을 승인한다. 소속 패턴이 반려 상태면 하지 않는다."""
    pattern, usage = _locked_usage(usage)
    _require(usage, ReviewStatus.PENDING)
    if pattern.status == ReviewStatus.REJECTED:
        raise Refused("반려된 패턴의 용법은 승인할 수 없습니다")
    usage.status = ReviewStatus.APPROVED
    usage.save(update_fields=["status", "updated_at"])


@transaction.atomic
def reject_usage(usage):
    """용법을 반려하고, 그 용법으로 정해진 구간이 있는 분석을 stale로 만든다."""
    pattern, usage = _locked_usage(usage)
    _require(usage, ReviewStatus.PENDING, ReviewStatus.APPROVED)
    usage.status = ReviewStatus.REJECTED
    usage.save(update_fields=["status", "updated_at"])
    # 패턴 쪽(용법 완결)을 분석 행보다 먼저 바꾼다(패턴 → 분석 순서).
    patterns.clear_usage_closed(pattern)
    patterns.make_stale(usages=[usage])


@transaction.atomic
def unreject_usage(usage):
    """반려를 취소해 미검수로 되돌리고, 그 패턴의 구간이 있는 분석을 stale로 만든다(되살아난
    용법을 다시 후보로 검토하게). 반려되지 않은 용법이 늘므로 용법 완결도 뗀다."""
    pattern, usage = _locked_usage(usage)
    _require(usage, ReviewStatus.REJECTED)
    if pattern.variant_of_id is not None:
        # 연결된 회화체는 자기 용법 없이 원형의 용법을 쓴다(#63).
        raise Refused("원형에 연결된 회화체의 자기 용법은 되살릴 수 없습니다")
    was_matchable = patterns.matchable_family(pattern)
    usage.status = ReviewStatus.PENDING
    usage.save(update_fields=["status", "updated_at"])
    if patterns.matchable_family(pattern) - was_matchable:
        # 매칭 자격을 다시 얻으면, 용법이 없는 동안 캐시된 문장에도 이 패턴의 구간이 생긴다(#41).
        patterns.raise_pattern_set_version()
    patterns.clear_usage_closed(pattern)
    patterns.make_stale(pattern=pattern)


@transaction.atomic
def unapprove_usage(usage):
    """승인을 취소해 미검수로 되돌리고, 그 용법으로 정해진 구간이 있는 분석을 stale로 만든다."""
    pattern, usage = _locked_usage(usage)
    _require(usage, ReviewStatus.APPROVED)
    usage.status = ReviewStatus.PENDING
    usage.save(update_fields=["status", "updated_at"])
    patterns.clear_usage_closed(pattern)
    patterns.make_stale(usages=[usage])


@transaction.atomic
def link_variant(pattern, base, mapping=None):
    """회화체 패턴을 원형에 연결한다(#63). 연결된 회화체는 원형의 용법을 후보로 쓴다.

    두 패턴(과 그 회화체들)을 한 번에 id 순서로 잠근다(patterns.lock_families). 그 회화체의
    구간이 있는 분석은 stale이 되고, 매칭 자격이 새로 생기면 패턴 세트 버전을 올린다.

    mapping은 회화체의 반려되지 않은 자기 용법마다 {용법 ID: 합칠 원형 용법 ID, 원형 아래로
    옮기면 None}이다. 자기 용법이 남았으면 모두 골라야 연결한다(#64). 이름으로 자동 대응하지
    않는다.
    """
    if pattern.pk == base.pk:
        raise Refused("원형으로 자기 자신을 고를 수 없습니다")
    patterns.lock_links(exclusive=True)
    locked = patterns.lock_families(base, pattern)
    base, pattern = locked[base.pk], locked[pattern.pk]
    if pattern.variant_of_id is not None:
        raise Refused("이미 원형에 연결돼 있습니다(바꾸려면 먼저 해제합니다)")
    # 연결된 회화체는 늘 register가 회화체이고, 연결을 푼 회화체도 회화체로 남는다.
    if base.register == GrammarPattern.Register.COLLOQUIAL:
        raise Refused("회화체 패턴은 원형이 될 수 없습니다")
    if GrammarPattern.objects.filter(variant_of=pattern).exists():
        raise Refused("이 패턴을 원형으로 가리키는 회화체가 있습니다")
    if ReviewStatus.REJECTED in {base.status, pattern.status}:
        raise Refused("반려된 패턴은 연결할 수 없습니다")
    mapping = mapping or {}
    merges = {source: target for source, target in mapping.items() if target is not None}
    moves = mapping.keys() - merges.keys()
    # 자기 용법과 합칠 원형 용법을 한 번에 id 순서로 잠근다(패턴 → 용법 순서).
    locked = (
        GrammarUsage.objects.select_for_update(no_key=True)
        .filter(Q(pattern=pattern) | Q(pattern=base, pk__in=merges.values()))
        .exclude(status=ReviewStatus.REJECTED)
        .order_by("id")
    )
    own = {u.pk: u for u in locked if u.pattern_id == pattern.pk}
    targets = {u.pk: u for u in locked if u.pattern_id == base.pk}
    if own and not mapping:
        raise Refused("반려되지 않은 자기 용법이 남아 있습니다(용법마다 합칠 원형 용법을 고릅니다)")
    if set(own) != set(mapping):
        raise Refused("고른 용법이 지금의 반려되지 않은 자기 용법과 다릅니다")
    if any(target not in targets for target in merges.values()):
        raise Refused("합칠 용법은 원형의 반려되지 않은 용법이어야 합니다")
    # 용법 이름은 패턴 안에서 유일하다(반려된 용법 포함). 반려된 용법으로는 합칠 수 없다.
    taken = dict(GrammarUsage.objects.filter(pattern=base).values_list("name", "status"))
    for source in moves:
        name = own[source].name
        if taken.get(name) == ReviewStatus.REJECTED:
            raise Refused(
                "원형의 같은 이름 용법이 반려돼 있어 옮길 수 없습니다(그 용법을 반려 취소한 뒤"
                f" 합치거나, 다른 용법으로 합치거나, 이 용법을 반려합니다): {name}"
            )
        if name in taken:
            raise Refused(
                f"원형에 같은 이름의 용법이 있어 옮길 수 없습니다(합침을 고릅니다): {name}"
            )
    # 원형도 본다. 옮긴 용법으로 원형(과 그 회화체들)이 매칭 자격을 얻을 수 있다(#64).
    was_matchable = patterns.matchable_family(pattern) | patterns.matchable_family(base)
    pattern.variant_of = base
    pattern.register = GrammarPattern.Register.COLLOQUIAL
    pattern.save(update_fields=["variant_of", "register"])
    for source in moves:
        _move_usage(own[source], base)
    # 버전은 분석 행을 잠그기(합침, stale) 전에 올린다.
    if patterns.matchable_family(base) - was_matchable:
        patterns.raise_pattern_set_version()
    if mapping:
        # 원형과 그 회화체들(이번에 연결한 것 포함)의 분석, 합치거나 옮길 용법을 주 용법·후보·
        # 대안으로 가리키는 분석을 다시 분석한다. 병합 전에 시작한 분석이 옛 소속으로 저장하지
        # 못하게 한다. 이 분석들을 먼저 한 번에 id 순서로 잠가, 뒤의 합침·용법 완결 떼기가 그
        # 일부를 다시 잠가도 기다리지 않게 한다. 분석 행을 id 순서로 잠그는 다른 사건과
        # 엇갈리지 않는다.
        patterns.make_stale(pattern=base, usages=own.values(), candidates=True)
    for source, target in merges.items():
        patterns.merge_usage(own[source], targets[target])
    if moves:
        # 옮김은 원형에 용법을 더한 것과 같다. 원형과 그 회화체들의 용법 완결을 뗀다.
        patterns.clear_usage_closed(base)
    patterns.clear_usage_closed(pattern)
    if not mapping:
        patterns.make_stale(pattern=pattern)


def _move_usage(usage, base):
    """회화체의 자기 용법을 원형 아래로 옮긴다(#64). 검수 상태는 그대로다. 예문이 원형 조건에
    걸리지 않으면(회화체 형태로 쓴 예문) 비운다.
    """
    usage.pattern = base
    if usage.example_ja is not None and not matches(patterns.conditions_of(base), usage.example_ja):
        usage.example_ja = None
    usage.save(update_fields=["pattern", "example_ja", "updated_at"])


@transaction.atomic
def unlink_variant(pattern):
    """회화체 패턴의 원형 연결을 푼다. register는 회화체로 남긴다(배지는 남고 안내 한 줄만
    사라진다). 원형으로 간 용법은 돌려받지 않아 자기 용법 0개로 매칭에서 빠진다. 자격을 잃는
    쪽이라 패턴 세트 버전은 올리지 않는다.
    """
    patterns.lock_links(exclusive=True)
    pattern, base = _locked_with_base(pattern)
    if base is None:
        raise Refused("원형에 연결돼 있지 않습니다")
    pattern.variant_of = None
    pattern.save(update_fields=["variant_of"])
    patterns.clear_usage_closed(pattern)
    patterns.make_stale(pattern=pattern)


def test_cases_refusal(pattern, cases):
    """패턴의 test_cases를 cases로 바꿀 수 없는 이유. 바꿀 수 있으면 None.

    승인됐거나 용법 완결인 패턴은 바꾼 뒤에도 test_cases를 통과해야 한다(먼저 승인을
    취소한다). 패턴 행을 잠그므로 같은 트랜잭션에서 update_test_cases를 부른다.
    """
    pattern = _locked(pattern)
    if pattern.status != ReviewStatus.APPROVED and not pattern.usage_closed:
        return None
    failure = test_cases_failure(pattern, cases)
    if failure:
        return f"승인·용법 완결 패턴은 test_cases를 통과해야 합니다(먼저 승인 취소): {failure}"
    return None


@transaction.atomic
def update_test_cases(pattern, cases):
    """test_cases를 바꾸고, 반려되지 않은 패턴이면 활성화 근거를 다시 확인해 is_active를 맞춘다."""
    refusal = test_cases_refusal(pattern, cases)
    if refusal:
        raise Refused(refusal)
    pattern = _locked(pattern)
    pattern.test_cases = cases
    pattern.save(update_fields=["test_cases"])
    if pattern.status != ReviewStatus.REJECTED:
        _set_active(pattern, _has_activation_basis(pattern))


def rule_test_cases_failure(rule, cases=None):
    """판별 규칙의 test_cases(주지 않으면 저장된 것)가 통과하지 못하는 이유. 통과하면 None(#55).

    '적용됨'·'적용 안 됨' 예문이 각각 하나 이상 있어야 한다. '적용됨'은 패턴이 걸리고 걸린 자리
    가운데 하나에서 조건이 맞아야 하고, '적용 안 됨'은 패턴은 걸리지만 걸린 어느 자리에서도
    조건이 맞지 않아야 한다. 패턴이 걸리지 않는 예문은 어느 쪽이든 실패다.
    """
    cases = rule.test_cases if cases is None else cases
    if not any(case["should_apply"] for case in cases):
        return "'적용됨' 예문이 없습니다"
    if all(case["should_apply"] for case in cases):
        return "'적용 안 됨' 예문이 없습니다"
    conditions = patterns.conditions_of(rule.pattern)
    for case in cases:
        analysis, _ = analysis_text(case["text"])
        morphs = morphemes(analysis) if analysis else []
        starts = patterns.match_starts(conditions, morphs)
        if not starts:
            return f"패턴이 걸리지 않는 예문입니다: {case['text']}"
        applies = any(
            condition_matches(rule.condition, morphs, start, start + len(conditions) - 1)
            for start in starts
        )
        if applies != case["should_apply"]:
            expected = "적용돼야" if case["should_apply"] else "적용되면 안 되"
            return f"{expected} 하는 예문이 기대와 다릅니다: {case['text']}"
    return None


def _locked_rule(rule):
    """규칙의 패턴(과 그 원형)을 잠근 뒤 규칙을 잠근다. 패턴 → 규칙 → 분석 순서다."""
    pattern, base = _locked_with_base(rule.pattern)
    locked = (
        UsageRule.objects.select_for_update(no_key=True).select_related("usage").get(pk=rule.pk)
    )
    # 잠그기 전에 읽은 패턴을 잠갔으므로, 그사이 미검수 규칙의 패턴이 바뀌었으면 하지 않는다.
    if locked.pattern_id != pattern.pk:
        raise Refused("그사이 규칙의 패턴이 바뀌었습니다")
    return pattern, base, locked


@transaction.atomic
def approve_rule(rule, user=None):
    """test_cases를 통과한 미검수 규칙을 승인한다. 패턴(연결됐으면 원형도)과 용법이 승인돼야
    한다. 그 패턴으로 매칭된 구간이 있는 분석만 stale로 만든다(새 규칙이 그 구간을 정할 수 있다,
    #55). 규칙은 실제로 매칭된 패턴에만 쓰므로 연결된 회화체 구간은 넣지 않는다.
    """
    pattern, base, rule = _locked_rule(rule)
    if rule.status != UsageRule.Status.PENDING:
        raise Refused(f"지금 상태({rule.get_status_display()})에서는 할 수 없습니다")
    if pattern.status != ReviewStatus.APPROVED or (
        base is not None and base.status != ReviewStatus.APPROVED
    ):
        raise Refused("규칙의 패턴이 승인돼야 합니다")
    # 그사이 원형 연결이 바뀌었으면 용법이 이 패턴의 후보가 아니어서 규칙이 쓰이지 않는다.
    if rule.usage.pattern_id != (base or pattern).pk:
        raise Refused("규칙의 용법이 그 패턴(연결된 회화체면 원형)의 용법이 아닙니다")
    if rule.usage.status != ReviewStatus.APPROVED:
        raise Refused("규칙의 용법이 승인돼야 합니다")
    failure = rule_test_cases_failure(rule)
    if failure:
        raise Refused(failure)
    rule.status = UsageRule.Status.APPROVED
    rule.approved_by = user
    rule.approved_at = timezone.now()
    rule.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    # 용법 완결 패턴의 구간은 2단계에서 먼저 확정되므로 규칙이 결과를 바꾸지 않는다. 용법 완결이
    # 풀릴 때 그 전이가 따로 stale로 만든다.
    if not pattern.usage_closed:
        patterns.make_stale(pattern=pattern, family=False)


@transaction.atomic
def retire_rule(rule):
    """규칙을 폐기한다. 되돌리지 않는다. 그 규칙으로 정해진 구간이 있는 분석만 stale로 만든다
    (미검수 규칙은 판정에 쓰인 적이 없다, #55).
    """
    _, _, rule = _locked_rule(rule)
    if rule.status == UsageRule.Status.RETIRED:
        raise Refused(f"지금 상태({rule.get_status_display()})에서는 할 수 없습니다")
    rule.status = UsageRule.Status.RETIRED
    rule.save(update_fields=["status", "updated_at"])
    patterns.make_stale(rule=rule)
