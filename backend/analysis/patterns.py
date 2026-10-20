"""문법 패턴: 형태소 조건, 매칭, 새 패턴 등록(#35).

패턴은 연속한 토큰의 형태소 조건이다. 조건 칸이 None이면 아무거나이고, 아무거나는 정확히
1토큰이다. 탁음화 조건부 규칙은 #36에서 더한다.
"""

import hashlib
from typing import NamedTuple

from django.db import IntegrityError, transaction
from django.db.models import F, Prefetch
from django.utils import timezone

from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternMorpheme,
    PatternSetVersion,
    ReviewStatus,
)


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


def _with_candidates(patterns):
    """패턴마다 형태소 조건(seq 순서)과 반려되지 않은 용법(등록 순서)을 함께 읽는다."""
    return patterns.prefetch_related(
        Prefetch("morphemes", queryset=PatternMorpheme.objects.order_by("seq")),
        Prefetch(
            "usages",
            queryset=GrammarUsage.objects.exclude(status=ReviewStatus.REJECTED).order_by("id"),
        ),
    ).order_by("id")


def _conditions(pattern):
    return [Condition(m.lemma, m.pos1, m.pos2, m.conjugation_form) for m in pattern.morphemes.all()]


def _numbered(usages, next_id):
    return [(next_id + i, usage) for i, usage in enumerate(usages)]


def candidate_spans(morphs):
    """활성 패턴을 형태소열에 대조해 구간마다 반려되지 않은 용법을 후보로 붙인다.

    후보 ID는 이 요청에서 서버가 1부터 매긴다. LLM은 이 ID로만 용법을 고른다.
    """
    spans = []
    next_id = 1
    for pattern in _with_candidates(GrammarPattern.objects.filter(is_active=True)):
        usages = list(pattern.usages.all())
        if not usages:
            continue
        conditions = _conditions(pattern)
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
    conditions = _conditions(pattern)
    usages = list(pattern.usages.all())
    return Span(pattern, conditions, start, start + len(conditions) - 1, _numbered(usages, next_id))


def register(conditions, pattern_name, usage_name, explanation_ko, example_ja):
    """새 패턴과 용법을 미검수로 등록한다. 같은 morpheme_key가 이미 있으면 (그 패턴, None).

    example_ja는 검사를 통과한 새 예문이고, 없으면 None이다. 예문이 있어야 활성화한다.
    활성화했으면 호출하는 쪽이 같은 트랜잭션에서 raise_pattern_set_version을 부른다.
    """
    pattern, created = GrammarPattern.objects.get_or_create(
        morpheme_key=morpheme_key(conditions),
        defaults={
            "name": pattern_name,
            "test_cases": [{"text": example_ja, "should_match": True}] if example_ja else [],
            "is_active": example_ja is not None,
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
        status=ReviewStatus.PENDING,
        origin=GrammarUsage.Origin.LLM,
    )
    return pattern, usage


def raise_pattern_set_version():
    """패턴 세트 버전을 1 올린다. UPDATE가 행을 잠그므로 동시에 올려도 하나씩 오른다."""
    PatternSetVersion.objects.filter(id=1).update(
        version=F("version") + 1, updated_at=timezone.now()
    )


def add_usage(pattern, name, explanation_ko, example_ja):
    """기존 패턴 아래 새 용법을 미검수로 더한다. 같은 이름의 용법이 이미 있으면 None.

    example_ja는 검사를 통과한 새 예문이고, 없으면 None이다. 호출하는 쪽이 트랜잭션을 연다.
    """
    try:
        # 같은 이름을 동시에 더하면 유일성 제약에 걸린다. 바깥 트랜잭션은 살려 둔다.
        with transaction.atomic():
            return GrammarUsage.objects.create(
                pattern=pattern,
                name=name,
                explanation_ko=explanation_ko,
                example_ja=example_ja,
                status=ReviewStatus.PENDING,
                origin=GrammarUsage.Origin.LLM,
            )
    except IntegrityError:
        return None
