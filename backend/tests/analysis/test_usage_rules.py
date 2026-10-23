"""승인된 판별 규칙으로 구간을 LLM 없이 확정(#55, 구간 판정 절차 3단계)."""

import pytest
from django.db import transaction

from analysis import patterns
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
    UsageRule,
)
from tests.analysis.helpers import analyze, new_pattern

pytestmark = pytest.mark.django_db

# 토큰: 0 東京 / 1 で / 2 会う
TOKYO_DE = "東京で会う"
AFTER_PLACE = [{"position": -1, "pos3": "地名"}]


def register_de(client, fake_llm, *more_usages):
    """수단 で를 등록하고 용법을 더한 뒤, 패턴과 모든 용법을 승인 상태로 둔다."""
    fake_llm.response = {
        "translation_ko": "버스로 간다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                pattern_name="で",
                usage_name="수단",
                explanation_ko="수단을 나타낸다",
                example_ja="車で行く",
            )
        ],
    }
    analyze(client, "バスで行く")
    pattern = GrammarPattern.objects.get()
    with transaction.atomic():
        for name in more_usages:
            patterns.add_usage(pattern, name, f"{name}을 나타낸다", None)
    GrammarPattern.objects.update(status=ReviewStatus.APPROVED)
    GrammarUsage.objects.update(status=ReviewStatus.APPROVED)
    fake_llm.forget_requests()
    return pattern


def rule(pattern, usage_name, condition=AFTER_PLACE, status=UsageRule.Status.APPROVED):
    return UsageRule.objects.create(
        pattern=pattern,
        usage=pattern.usages.get(name=usage_name),
        condition=condition,
        status=status,
    )


def test_span_decided_by_an_approved_rule_is_not_asked_and_shown_first(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    place = rule(pattern, "장소")
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}

    response = analyze(client, TOKYO_DE)

    [request] = fake_llm.requests
    assert request["spans"] == []
    assert request["decided_spans"] == [{"start_token_id": 1, "end_token_id": 1, "name": "장소"}]
    assert response.types()[0] == "grammar"
    assert response.events[0]["grammar"] == [
        {
            "start": 2,
            "end": 3,
            "state": "decided",
            "name": "장소",
            "explanation_ko": "장소을 나타낸다",
            "review_status": "approved",
            "register": "standard",
            "variant_of": None,
        }
    ]
    assert response.events[0]["checking"] == []
    span = SpanMatch.objects.get(analysis=SentenceAnalysis.objects.latest("id"))
    assert (span.state, span.decided_by, span.rule) == ("decided", "rule", place)
    assert response.json()["grammar"] == response.events[0]["grammar"]


def asked_spans(fake_llm):
    return [
        [candidate["name"] for candidate in span["candidates"]]
        for span in fake_llm.requests[-1]["spans"]
    ]


def unapprove(model, name):
    model.objects.filter(name=name).update(status=ReviewStatus.PENDING)


BOTH = [["수단", "장소"]]


@pytest.mark.parametrize(
    ("spoil", "expected"),
    [
        (lambda pattern: rule(pattern, "장소", status=UsageRule.Status.PENDING), BOTH),
        (lambda pattern: rule(pattern, "장소", status=UsageRule.Status.RETIRED), BOTH),
        (lambda pattern: (rule(pattern, "장소"), unapprove(GrammarPattern, "で")), BOTH),
        (lambda pattern: (rule(pattern, "장소"), unapprove(GrammarUsage, "장소")), BOTH),
        # 반려된 용법은 후보에서 빠진다.
        (
            lambda pattern: (
                rule(pattern, "장소"),
                GrammarUsage.objects.filter(name="장소").update(status=ReviewStatus.REJECTED),
            ),
            [["수단"]],
        ),
    ],
    ids=["pending", "retired", "pattern-pending", "usage-pending", "usage-rejected"],
)
def test_unusable_rules_leave_the_span_to_the_llm(client, fake_llm, spoil, expected):
    spoil(register_de(client, fake_llm, "장소"))
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}

    analyze(client, TOKYO_DE)

    assert asked_spans(fake_llm) == expected
    assert not SpanMatch.objects.filter(decided_by="rule").exists()


def test_rule_of_another_pattern_is_not_used(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    fake_llm.response = {
        "translation_ko": "만난다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                pattern_name="に",
                usage_name="도착점",
                explanation_ko="도착점을 나타낸다",
                example_ja="駅に着く",
            )
        ],
    }
    analyze(client, "家に帰る")
    other = GrammarPattern.objects.get(name="に")
    UsageRule.objects.create(
        pattern=other,
        usage=pattern.usages.get(name="장소"),
        condition=AFTER_PLACE,
        status=UsageRule.Status.APPROVED,
    )
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}

    analyze(client, TOKYO_DE)

    assert asked_spans(fake_llm) == BOTH


def test_rules_pointing_at_different_usages_leave_the_span_to_the_llm(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    rule(pattern, "장소")
    rule(pattern, "수단", condition=[{"position": 1, "lemma": "会う"}])
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}

    analyze(client, TOKYO_DE)

    assert asked_spans(fake_llm) == BOTH


def test_several_rules_for_the_same_usage_record_the_smallest_id(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    first = rule(pattern, "장소")
    rule(pattern, "장소", condition=[{"position": 1, "lemma": "会う"}])
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}

    analyze(client, TOKYO_DE)

    assert asked_spans(fake_llm) == []
    assert SpanMatch.objects.get(decided_by="rule").rule == first


def test_rule_whose_condition_does_not_hold_leaves_the_span_to_the_llm(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    rule(pattern, "장소")
    fake_llm.response = {"translation_ko": "택시로 간다"}

    # タクシー는 지명이 아니다.
    analyze(client, "タクシーで行く")

    assert asked_spans(fake_llm) == BOTH


def test_rule_decides_a_single_candidate_and_ignores_other_pending_usages(client, fake_llm):
    pattern = register_de(client, fake_llm)
    rule(pattern, "수단", condition=[{"position": 1, "pos1": "動詞"}])
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}

    analyze(client, TOKYO_DE)
    assert asked_spans(fake_llm) == []

    # 미검수 용법이 더해져 후보가 둘이어도, 승인된 용법을 가리키는 규칙만 맞으면 확정한다.
    with transaction.atomic():
        patterns.add_usage(pattern, "장소", "장소를 나타낸다", None)
    fake_llm.response = {"translation_ko": "버스로 만난다"}

    analyze(client, "バスで会う")

    assert asked_spans(fake_llm) == []
    assert SpanMatch.objects.filter(decided_by="rule").count() == 2


def test_cached_analysis_with_a_rule_decided_span_is_reused_without_the_llm(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    rule(pattern, "장소")
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}
    first = analyze(client, TOKYO_DE)

    again = analyze(client, TOKYO_DE)

    assert len(fake_llm.requests) == 1
    assert again.json()["grammar"] == first.json()["grammar"]
