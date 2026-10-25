"""문법 패턴: 형태소 조건, 매칭, 새 패턴 등록(#35).

패턴은 연속한 토큰의 형태소 조건이다. 조건 칸이 None이면 아무거나이고, 아무거나는 정확히
1토큰이다. 탁음화 조건부 규칙은 #36에서 더한다.
"""

import hashlib
import operator
from functools import reduce
from typing import NamedTuple

from django.db import IntegrityError, connection, transaction
from django.db.models import Exists, F, OuterRef, Prefetch, Q
from django.utils import timezone

from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternMorpheme,
    PatternSetVersion,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
    UsageRule,
)

# 새 예문(용법 예문, test_cases)은 짧은 문장으로 받는다. 이보다 길면 쓰지 않는다. 형태소 분석
# 한도(49,149바이트)보다 훨씬 짧아 분석이 실패하지 않고, 부분 복사 검사도 원문 길이 × 이 길이
# 안에서 끝난다.
EXAMPLE_MAX_LENGTH = 200


class Condition(NamedTuple):
    lemma: str | None
    pos1: str | None
    pos2: str | None
    conjugation_form: str | None


ANY = Condition(None, None, None, None)


def condition(morph, fix):
    """LLM이 표시한 토큰(lemma 고정 / 활용형도 고정 / 아무거나)의 형태소 조건."""
    if fix == "any":
        return ANY
    conjugation_form = morph.conjugation_form if fix == "form" else None
    return Condition(morph.lemma, morph.pos, morph.pos2, conjugation_form)


def morpheme_key(conditions):
    """형태소 조건(lemma|pos1|pos2|conj, 아무거나는 *)을 순서대로 이은 문자열의 SHA-256."""
    rows = ("|".join(value or "*" for value in c) for c in conditions)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _fits(c, morph):
    values = (morph.lemma, morph.pos, morph.pos2, morph.conjugation_form)
    return all(want is None or want == value for want, value in zip(c, values, strict=True))


def matches_at(conditions, morphs, start):
    if start + len(conditions) > len(morphs):
        return False
    return all(_fits(c, morphs[start + i]) for i, c in enumerate(conditions))


def match_starts(conditions, morphs):
    return [i for i in range(len(morphs)) if matches_at(conditions, morphs, i)]


class Span(NamedTuple):
    """등록된 패턴에 걸린 구간. candidates는 (후보 ID, 용법)이다."""

    pattern: GrammarPattern
    conditions: list
    start_token: int
    end_token: int
    candidates: list


def _open_usages():
    return GrammarUsage.objects.exclude(status=ReviewStatus.REJECTED)


def _with_candidates(patterns):
    """패턴마다 형태소 조건(seq 순서)과 반려되지 않은 용법(등록 순서)을 함께 읽는다. 연결된
    회화체면 원형과 원형의 형태소 조건·용법도 읽는다.
    """
    morphemes = PatternMorpheme.objects.order_by("seq")
    usages = _open_usages().order_by("id")
    return (
        patterns.select_related("variant_of")
        .prefetch_related(
            Prefetch("morphemes", queryset=morphemes),
            Prefetch("usages", queryset=usages),
            Prefetch("variant_of__morphemes", queryset=morphemes),
            Prefetch("variant_of__usages", queryset=usages),
        )
        .order_by("id")
    )


def candidate_usages(pattern):
    """후보가 될 용법(등록 순서). 연결된 회화체면 원형의 반려되지 않은 용법이고 원형이 반려됐으면
    없다. 그 밖에는 자기 반려되지 않은 용법이다(#63). _with_candidates로 읽은 패턴에 쓴다.
    """
    base = pattern.variant_of
    if base is None:
        return list(pattern.usages.all())
    if base.status == ReviewStatus.REJECTED:
        return []
    return list(base.usages.all())


def matchable_patterns():
    """매칭 자격이 있는 패턴: 활성이고 후보가 될 용법(candidate_usages)이 하나 이상이다.
    candidate_spans가 매칭에 쓰는 패턴이고, 이 판정이 거짓에서 참이 되면 패턴 세트 버전을
    올린다(#41, #63).
    """
    own = Exists(_open_usages().filter(pattern=OuterRef("pk")))
    base = Exists(_open_usages().filter(pattern=OuterRef("variant_of")))
    return GrammarPattern.objects.filter(is_active=True).filter(
        Q(own, variant_of__isnull=True) | (Q(base) & ~Q(variant_of__status=ReviewStatus.REJECTED))
    )


def conditions_of(pattern):
    """패턴의 형태소 조건(seq 순서). 미리 읽어 둔 형태소가 있으면 그것을 쓴다."""
    morphemes = sorted(pattern.morphemes.all(), key=lambda m: m.seq)
    return [Condition(m.lemma, m.pos1, m.pos2, m.conjugation_form) for m in morphemes]


def _numbered(usages, next_id):
    return [(next_id + i, usage) for i, usage in enumerate(usages)]


def candidate_spans(morphs):
    """활성 패턴을 형태소열에 대조해 구간마다 반려되지 않은 용법을 후보로 붙인다.

    후보 ID는 이 요청에서 서버가 1부터 매긴다. LLM은 이 ID로만 용법을 고른다.
    """
    spans = []
    next_id = 1
    for pattern in _with_candidates(matchable_patterns()):
        usages = candidate_usages(pattern)
        # 용법은 따로 읽으므로 그사이 모두 반려됐을 수 있다.
        if not usages:
            continue
        conditions = conditions_of(pattern)
        for start in match_starts(conditions, morphs):
            spans.append(
                Span(
                    pattern,
                    conditions,
                    start,
                    start + len(conditions) - 1,
                    _numbered(usages, next_id),
                )
            )
            next_id += len(usages)
    return spans


def existing_patterns(conditions_list):
    """형태소 조건마다 같은 morpheme_key로 이미 있는 패턴(후보 용법을 함께 읽음). 없으면 없음."""
    keys = {morpheme_key(conditions) for conditions in conditions_list}
    found = _with_candidates(GrammarPattern.objects.filter(morpheme_key__in=keys))
    return {pattern.morpheme_key: pattern for pattern in found}


def span_of(pattern, start, next_id):
    """이미 있는 패턴을 start 토큰에서 시작하는 구간으로 다시 물을 때의 구간과 후보."""
    conditions = conditions_of(pattern)
    usages = candidate_usages(pattern)
    return Span(pattern, conditions, start, start + len(conditions) - 1, _numbered(usages, next_id))


def register(
    conditions,
    pattern_name,
    usage_name,
    explanation_ko,
    example_ja,
    test_example,
    korean_equivalent=None,
):
    """새 패턴과 용법을 미검수로 등록한다. 같은 morpheme_key가 이미 있으면 (그 패턴, None).

    example_ja는 이 용법이 쓴 예문, test_example은 같은 조건의 제안 중 검사를 통과한 예문이다
    (첫 test_cases 항목). 없으면 None이고, test_example이 있어야 활성화한다. 활성화했으면
    호출하는 쪽이 같은 트랜잭션에서 raise_pattern_set_version을 부른다. korean_equivalent는
    검증한 대응 표현이고 없으면 None이다(#152).
    """
    pattern, created = GrammarPattern.objects.get_or_create(
        morpheme_key=morpheme_key(conditions),
        defaults={
            "name": pattern_name,
            "test_cases": [{"text": test_example, "should_match": True}] if test_example else [],
            "is_active": test_example is not None,
            "status": ReviewStatus.PENDING,
        },
    )
    if not created:
        return pattern, None
    PatternMorpheme.objects.bulk_create(
        PatternMorpheme(pattern=pattern, seq=seq, **c._asdict()) for seq, c in enumerate(conditions)
    )
    usage = GrammarUsage.objects.create(
        pattern=pattern,
        name=usage_name,
        explanation_ko=explanation_ko,
        example_ja=example_ja,
        # LLM이 용법과 함께 답했으므로 비었어도 채운 것이다.
        korean_equivalent=korean_equivalent,
        korean_equivalent_filled=True,
        korean_equivalent_status=equivalent_status(korean_equivalent),
        status=ReviewStatus.PENDING,
        origin=GrammarUsage.Origin.LLM,
    )
    return pattern, usage


def equivalent_status(korean_equivalent):
    """LLM이 쓴 대응 표현의 검수 상태. 값이 있으면 미검수, 없으면 NULL이다(#152)."""
    return ReviewStatus.PENDING if korean_equivalent else None


def pattern_set_version():
    """현재 패턴 세트 버전."""
    return PatternSetVersion.objects.values_list("version", flat=True).get(id=1)


def raise_pattern_set_version():
    """패턴 세트 버전을 1 올린다. UPDATE가 행을 잠그므로 동시에 올려도 하나씩 오른다."""
    PatternSetVersion.objects.filter(id=1).update(
        version=F("version") + 1, updated_at=timezone.now()
    )


# 원형 연결 상태의 advisory 잠금 열쇠(#63)
_LINKS_LOCK = 63_000_001


def lock_links(exclusive=False):
    """원형 연결 상태를 트랜잭션이 끝날 때까지 잠근다. 연결·해제는 배타로, 구간을 저장하는 분석은
    공유로 잡아 분석끼리는 막지 않는다. 연결·해제가 저장 중인(커밋 전) 구간을 stale로 만들지
    못하고 지나가지 않게 한다. 다른 잠금보다 먼저, 트랜잭션 맨 처음에 잡는다(#63).
    """
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {function}(%s)", [_LINKS_LOCK])


def lock_families(*patterns):
    """패턴들과, 그 패턴을 원형으로 가리키는 회화체들을 한 번에 id 순서로 잠근다(#63).

    원형 쪽 사건은 연결된 회화체까지 바꾸고, 연결·해제와 한 문장의 새 용법들은 여러 패턴을 함께
    잠근다. 패턴을 잠그는 모든 경로가 이 함수로 한 번에 잠가 순서를 맞춘다. 잠금은 FOR NO KEY
    UPDATE다(analysis.review). {id: 잠근 패턴}을 돌려준다.
    """
    ids = {pattern.pk for pattern in patterns}
    family = Q(pk__in=ids) | Q(variant_of__in=ids)
    rows = GrammarPattern.objects.select_for_update(no_key=True).filter(family).order_by("id")
    return {row.pk: row for row in rows}


def matchable_family(pattern):
    """그 패턴과 그 패턴을 원형으로 가리키는 회화체 중 매칭 자격이 있는 것의 ID들(#63)."""
    family = matchable_patterns().filter(Q(pk=pattern.pk) | Q(variant_of=pattern))
    return set(family.values_list("pk", flat=True))


def add_usage(pattern, name, explanation_ko, example_ja, matched=None, korean_equivalent=None):
    """기존 패턴 아래 새 용법을 미검수로 더한다. (용법, 매칭 자격을 새로 얻은 패턴이 있는가)를
    돌려준다. 같은 이름의 용법이 이미 있으면 (None, False)다.

    matched는 이 용법이 설명할 구간의 실제로 매칭된 패턴이고, 주지 않으면 pattern이다. 연결된
    회화체면 pattern은 그 원형이다. 패턴을 잠근 뒤 연결 상태가 그대로인지(matched가 pattern이면
    연결되지 않음, 아니면 pattern에 연결됨) 다시 보고, 바뀌었으면 더하지 않고 (None, False)다.
    연결된 회화체에는 자기 용법을 두지 않는다(#63).

    example_ja는 검사를 통과한 새 예문이고, 없으면 None이다. korean_equivalent는 검증한 대응
    표현이고 없으면 None이다(#152). 호출하는 쪽이 트랜잭션을 열고,
    매칭 자격을 새로 얻었으면 분석 행을 잠그기 전에 패턴 세트 버전을 한 번 올린다(잠금 순서:
    패턴과 그 회화체(lock_families) → 용법 → 버전 → 분석).
    """
    # 패턴을 먼저 잠가, 용법 완결 표시(analysis.review)가 커밋 전 용법을 못 본 채 하나라고
    # 판단하지 않게 한다. 상태 전이와 같은 패턴 → 분석 순서다. 연결·해제도 이 패턴을 잠그므로
    # 그 뒤 읽은 연결 상태는 이 트랜잭션이 끝날 때까지 바뀌지 않는다.
    lock_families(pattern)
    matched_id = (matched or pattern).pk
    # 자기 패턴에 더하면 그 패턴은 아직 회화체로 연결되지 않아야 하고, 원형에 더하면 매칭된
    # 회화체가 아직 그 원형에 연결돼 있어야 한다.
    expected_base = None if matched_id == pattern.pk else pattern.pk
    linked_to = GrammarPattern.objects.values_list("variant_of_id", flat=True).get(pk=matched_id)
    if linked_to != expected_base:
        return None, False
    was_matchable = matchable_family(pattern)
    try:
        # 같은 이름을 동시에 더하면 유일성 제약에 걸린다. 바깥 트랜잭션은 살려 둔다.
        with transaction.atomic():
            usage = GrammarUsage.objects.create(
                pattern=pattern,
                name=name,
                explanation_ko=explanation_ko,
                example_ja=example_ja,
                korean_equivalent=korean_equivalent,
                korean_equivalent_filled=True,
                korean_equivalent_status=equivalent_status(korean_equivalent),
                status=ReviewStatus.PENDING,
                origin=GrammarUsage.Origin.LLM,
            )
    except IntegrityError:
        return None, False
    # 용법이 둘이 되면 더는 용법 완결이 아니다(그 패턴에 연결된 회화체도).
    clear_usage_closed(pattern)
    return usage, bool(matchable_family(pattern) - was_matchable)


def clear_usage_closed(pattern):
    """그 패턴과, 그 패턴을 원형으로 가리키는 회화체의 용법 완결을 뗀다. 회화체의 용법 완결은
    원형의 용법에 기대므로 원형 쪽 사건이 함께 뗀다(#63). 뗐으면 그 패턴(과 회화체)의 구간이
    있는 분석을 stale로 만든다. 호출하는 쪽이 lock_families로 회화체까지 잠가 둔다.
    """
    family = Q(pk=pattern.pk) | Q(variant_of=pattern)
    if GrammarPattern.objects.filter(family, usage_closed=True).update(usage_closed=False):
        pattern.usage_closed = False
        make_stale(pattern=pattern)


def make_stale(pattern=None, usages=(), candidates=False, rule=None, family=True):
    """그 패턴(과 그 패턴을 원형으로 가리키는 회화체)으로 매칭된 구간, 그 용법들로 정해진 구간이나
    그 용법을 대안으로 쓴 해석 갈림 구간, 또는 그 판별 규칙으로 정해진 구간이 있는 분석을 stale로
    만들고 세대 번호를 올린다(#38, #40, #63, #55). 회화체 구간도 원형 용법을 쓰므로 용법 쪽은
    따로 넓히지 않는다. 동시에 여러 사건이 겹쳐도 교착하지 않게 id 순서로 잠근 뒤 바꾼다. 잠근
    분석 ID들을 돌려준다.

    패턴과 용법을 함께 주면 어느 쪽에든 걸리는 분석을 한 번에 잠근다. candidates면 그 용법을
    후보로만 가진 구간의 분석도 넣는다. 용법 참조를 옮길 때 쓴다(#64). family가 거짓이면 그 패턴
    자체로 매칭된 구간만 본다(판별 규칙은 실제로 매칭된 패턴에만 적용된다, #55).
    """
    span_filters = []
    if pattern is not None:
        span_filters.append(Q(span_matches__pattern=pattern))
        if family:
            span_filters.append(Q(span_matches__pattern__variant_of=pattern))
    for usage in usages:
        span_filters += [
            Q(span_matches__usage=usage),
            Q(span_matches__alternatives__contains=[{"usage_id": usage.id}]),
        ]
        if candidates:
            span_filters.append(Q(span_matches__candidates__contains=[{"usage_id": usage.id}]))
    if rule is not None:
        span_filters.append(Q(span_matches__rule=rule))
    span_filter = reduce(operator.or_, span_filters)
    ids = list(
        SentenceAnalysis.objects.filter(
            id__in=SentenceAnalysis.objects.filter(span_filter).values("id")
        )
        .order_by("id")
        .select_for_update(no_key=True)
        .values_list("id", flat=True)
    )
    SentenceAnalysis.objects.filter(id__in=ids).update(
        is_stale=True, generation=F("generation") + 1
    )
    return ids


def merge_usage(source, target):
    """source 용법을 target으로 합친다(#64). 구간이 source를 주 용법·후보·대안으로 가리키던
    참조를 target으로 바꾸고 source를 지운다. 바꾼 구간에서 겹친 후보는 앞의 것만 남기고, 주
    용법과 같아졌거나 앞 대안과 겹친 대안은 뺀다. 대안이 남지 않은 해석 갈림은 decided가 된다.
    source를 가리키던 판별 규칙도 target을 가리키게 한다(#55).

    그 구간이 있는 분석을 먼저 잠가 stale로 만들고 세대 번호를 올린 뒤 구간을 바꾼다(구간은 분석
    행을 잠근 뒤 쓴다). 호출하는 쪽이 두 용법과 그 패턴을 잠그고, lock_links(배타)로 구간을
    저장하는 분석과 직렬화해 그사이 source를 가리키는 구간이 저장되지 않게 한다. 지운 용법을
    가리키는 구간이 커밋되면 FK 검사에 걸린다. 패턴 합치기(FR-A27)나 관리자 정정이 용법 참조를
    옮길 때도 쓸 수 있게 회화체 연결과 따로 둔다.
    """
    ids = make_stale(usages=[source], candidates=True)
    rows = [
        row
        for row in SpanMatch.objects.filter(analysis_id__in=ids).order_by("id")
        if _repointed(row, source.pk, target.pk)
    ]
    SpanMatch.objects.bulk_update(rows, ["usage", "state", "candidates", "alternatives"])
    # 판별 규칙도 target을 가리킨다. 같은 뜻으로 합친 용법이라 규칙의 뜻은 그대로다(#55).
    UsageRule.objects.filter(usage=source).update(usage=target, updated_at=timezone.now())
    source.delete()


def _repointed(row, source_id, target_id):
    """구간의 source 참조를 target으로 바꾸고 겹친 후보·대안을 정리한다. source를 가리키지 않던
    구간이면 그대로 두고 False다.
    """
    items = (row.candidates or []) + (row.alternatives or [])
    if row.usage_id != source_id and all(item["usage_id"] != source_id for item in items):
        return False

    def kept(items, taken):
        # 바꾼 뒤 이미 나온 용법이면 뺀다(앞의 것을 남긴다).
        result = []
        for item in items:
            usage_id = target_id if item["usage_id"] == source_id else item["usage_id"]
            if usage_id not in taken:
                taken.add(usage_id)
                result.append({**item, "usage_id": usage_id})
        return result

    if row.usage_id == source_id:
        row.usage_id = target_id
    if row.candidates is not None:
        row.candidates = kept(row.candidates, set())
    if row.alternatives is not None:
        # 주 용법과 같아진 대안도 뺀다. 대안이 남지 않으면 해석이 갈리지 않은 것이다.
        row.alternatives = kept(row.alternatives, {row.usage_id}) or None
        if row.alternatives is None:
            row.state = SpanMatch.State.DECIDED
    return True
