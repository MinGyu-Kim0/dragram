"""문법 패턴: 형태소 조건, 매칭, 새 패턴 등록(#35).

패턴은 연속한 토큰의 형태소 조건이다. 조건 칸이 None이면 아무거나이고, 아무거나는 정확히
1토큰이다. 탁음화 조건부 규칙은 #36에서 더한다.
"""

import hashlib
from typing import NamedTuple

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
    start_token: int
    end_token: int
    candidates: list


def candidate_spans(morphs):
    """활성 패턴을 형태소열에 대조해 구간마다 반려되지 않은 용법을 후보로 붙인다.

    후보 ID는 이 요청에서 서버가 1부터 매긴다. LLM은 이 ID로만 용법을 고른다.
    """
    patterns = GrammarPattern.objects.filter(is_active=True).prefetch_related(
        Prefetch("morphemes", queryset=PatternMorpheme.objects.order_by("seq")),
        Prefetch(
            "usages",
            queryset=GrammarUsage.objects.exclude(status=ReviewStatus.REJECTED).order_by("id"),
        ),
    )
    spans = []
    next_id = 1
    for pattern in patterns.order_by("id"):
        usages = list(pattern.usages.all())
        if not usages:
            continue
        conditions = [
            Condition(m.lemma, m.pos1, m.pos2, m.conjugation_form) for m in pattern.morphemes.all()
        ]
        for start in match_starts(conditions, morphs):
            candidates = [(next_id + i, usage) for i, usage in enumerate(usages)]
            next_id += len(usages)
            spans.append(Span(pattern, start, start + len(conditions) - 1, candidates))
    return spans


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
