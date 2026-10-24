"""분석 텍스트에서 계산되는 값. 요청과 작업자가 함께 쓴다."""

from analysis.models import (
    ReviewStatus,
    UsageRule,
)
from analysis.normalize import (
    number_ends,
)
from analysis.rules import condition_matches


def _numbers_before_particle(text, morphs):
    """원문에서 바로 뒤에 조사(助詞)가 오는 숫자의 자리표시자 번호."""
    particle_starts = {m.begin for m in morphs if m.pos == "助詞"}
    return {n for n, end in enumerate(number_ends(text), start=1) if end in particle_starts}


# 학습할 단어가 아닌 토큰의 품사(문장부호, 공백, 문법 쪽에서 다루는 조사·조동사)
_NON_WORD_POS = {"補助記号", "空白", "助詞", "助動詞"}


def _pattern_statuses(pattern):
    """매칭된 패턴과, 연결됐으면 그 원형의 검수 상태들(#63)."""
    base = pattern.variant_of
    return {pattern.status} | ({base.status} if base else set())


def _closed_usage(span):
    """용법 완결로 LLM 없이 확정할 구간이면 (후보 ID, 그 용법), 아니면 None(구간 판정 절차
    2단계). 승인된 용법 완결 패턴이고, 반려되지 않은 용법이 승인된 하나뿐이어야 한다. 용법 완결
    표시가 보장하지만 분석 때도 다시 본다.
    """
    pattern = span.pattern
    # 연결된 회화체는 원형도 승인돼야 한다. 후보는 원형의 용법이다(#63).
    if not pattern.usage_closed or _pattern_statuses(pattern) != {ReviewStatus.APPROVED}:
        return None
    if len(span.candidates) != 1:
        return None
    candidate = span.candidates[0]
    return candidate if candidate[1].status == ReviewStatus.APPROVED else None


def _approved_rules(spans):
    """구간들의 매칭된 패턴에 걸린 승인된 판별 규칙. {패턴 ID: [규칙](id 순서)}(#55)."""
    rules = {}
    approved = UsageRule.objects.filter(
        status=UsageRule.Status.APPROVED, pattern__in={span.pattern.pk for span in spans}
    ).order_by("id")
    for rule in approved:
        rules.setdefault(rule.pattern_id, []).append(rule)
    return rules


def _rule_usage(span, morphs, rules):
    """승인된 판별 규칙으로 LLM 없이 확정할 구간이면 (후보 ID, 용법, 규칙), 아니면 None(구간 판정
    절차 3단계, #55). 후보가 하나여도, 같은 패턴에 미검수 용법이 있어도 적용한다.

    실제로 매칭된 패턴의 규칙 가운데 패턴(연결됐으면 원형도)과 용법이 승인됐고 용법이 후보에 있는
    것만 본다. 분석할 때 상태를 다시 본다. 조건이 맞는 규칙들이 가리키는 후보가 정확히 하나일
    때만 확정하고, 같은 용법을 가리키는 규칙이 여럿 맞으면 id가 가장 작은 규칙을 기록한다.
    """
    if _pattern_statuses(span.pattern) != {ReviewStatus.APPROVED}:
        return None
    candidates = {usage.id: (candidate_id, usage) for candidate_id, usage in span.candidates}
    decided = {}
    for rule in rules.get(span.pattern.pk, ()):
        candidate = candidates.get(rule.usage_id)
        if candidate is None or candidate[1].status != ReviewStatus.APPROVED:
            continue
        if condition_matches(rule.condition, morphs, span.start_token, span.end_token):
            decided.setdefault(rule.usage_id, rule)
    if len(decided) != 1:
        return None
    [(usage_id, rule)] = decided.items()
    return (*candidates[usage_id], rule)


def _llm_spans(spans):
    """LLM에 줄 후보 구간. 구간 ID는 이 목록의 순번이다. 원형에 연결된 회화체 구간은 원형 패턴
    이름(colloquial_of)을 함께 준다. 후보는 원형의 용법이다(#63).
    """
    return [
        {
            "span_id": span_id,
            "start_token_id": span.start_token,
            "end_token_id": span.end_token,
            **({"colloquial_of": span.pattern.variant_of.name} if span.pattern.variant_of else {}),
            "candidates": [
                {"candidate_id": candidate_id, "name": u.name, "explanation_ko": u.explanation_ko}
                for candidate_id, u in span.candidates
            ],
        }
        for span_id, span in enumerate(spans)
    ]


def _is_fresh(analysis):
    """다시 분석하지 않고 쓸 수 있는 분석인가."""
    return analysis.word_spans is not None and not analysis.is_stale
