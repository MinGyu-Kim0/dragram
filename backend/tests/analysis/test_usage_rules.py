"""승인된 판별 규칙으로 구간을 LLM 없이 확정(#55, 구간 판정 절차 3단계)."""

import pytest
from django.db import transaction

from analysis import patterns, review
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
    UsageRule,
)
from tests.analysis.helpers import analyze, new_pattern, span_answer

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


def test_rematched_cached_sentence_gets_its_rule_decided_span_without_the_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}
    analyze(client, TOKYO_DE)
    # 그 뒤 で를 등록하면 패턴 세트 버전이 올라 캐시 문장을 다시 매칭한다(#41).
    rule(register_de(client, fake_llm, "장소"), "장소")

    response = analyze(client, TOKYO_DE)

    assert fake_llm.all_requests() == []
    assert [item["name"] for item in response.json()["grammar"]] == ["장소"]
    analysis = SentenceAnalysis.objects.get(translation_ko="도쿄에서 만난다")
    assert analysis.span_matches.get().decided_by == "rule"


# 규칙 test_cases. '적용됨'은 패턴이 걸리고 조건도 맞고, '적용 안 됨'은 패턴은 걸리지만
# 조건이 맞지 않는다.
PASSING = [
    {"text": "大阪で働く", "should_apply": True},
    {"text": "電車で通う", "should_apply": False},
]


def pending_rule(client, fake_llm, cases=PASSING):
    pattern = register_de(client, fake_llm, "장소")
    return rule(pattern, "장소", status=UsageRule.Status.PENDING), pattern


def test_approving_a_rule_makes_the_analyses_of_its_pattern_stale(client, fake_llm):
    usage_rule, _ = pending_rule(client, fake_llm)
    usage_rule.test_cases = PASSING
    usage_rule.save()
    analyses = SentenceAnalysis.objects.all()
    generations = {a.id: a.generation for a in analyses}
    version = patterns.pattern_set_version()

    review.approve_rule(usage_rule)

    usage_rule.refresh_from_db()
    assert usage_rule.status == UsageRule.Status.APPROVED
    assert usage_rule.approved_at is not None
    for analysis in SentenceAnalysis.objects.all():
        assert analysis.is_stale
        assert analysis.generation == generations[analysis.id] + 1
    assert patterns.pattern_set_version() == version


@pytest.mark.parametrize(
    "cases",
    [
        [],
        PASSING[:1],
        PASSING[1:],
        # 패턴이 걸리지 않는 예문은 어느 쪽이든 실패다.
        [*PASSING, {"text": "東京に行く", "should_apply": False}],
        # 기대와 다른 예문
        [*PASSING, {"text": "タクシーで行く", "should_apply": True}],
        [*PASSING, {"text": "京都で遊ぶ", "should_apply": False}],
    ],
)
def test_rule_without_passing_test_cases_is_not_approved(client, fake_llm, cases):
    usage_rule, _ = pending_rule(client, fake_llm)
    usage_rule.test_cases = cases
    usage_rule.save()

    with pytest.raises(review.Refused):
        review.approve_rule(usage_rule)

    usage_rule.refresh_from_db()
    assert usage_rule.status == UsageRule.Status.PENDING


@pytest.mark.parametrize("unapproved", [GrammarPattern, GrammarUsage])
def test_rule_of_an_unapproved_pattern_or_usage_is_not_approved(client, fake_llm, unapproved):
    usage_rule, _ = pending_rule(client, fake_llm)
    usage_rule.test_cases = PASSING
    usage_rule.save()
    unapproved.objects.update(status=ReviewStatus.PENDING)

    with pytest.raises(review.Refused):
        review.approve_rule(usage_rule)

    usage_rule.refresh_from_db()
    assert usage_rule.status == UsageRule.Status.PENDING


def test_retiring_a_rule_makes_only_the_analyses_it_decided_stale(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    place = rule(pattern, "장소")
    fake_llm.response = {"translation_ko": "버스로 간다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, "バスで行く")
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}
    analyze(client, TOKYO_DE)
    decided = SentenceAnalysis.objects.get(translation_ko="도쿄에서 만난다")
    other = SentenceAnalysis.objects.get(translation_ko="버스로 간다")
    version = patterns.pattern_set_version()

    review.retire_rule(place)

    place.refresh_from_db()
    assert place.status == UsageRule.Status.RETIRED
    decided.refresh_from_db()
    other.refresh_from_db()
    assert (decided.is_stale, other.is_stale) == (True, False)
    assert patterns.pattern_set_version() == version


def test_pending_rule_can_be_retired_but_a_retired_rule_cannot_come_back(client, fake_llm):
    usage_rule, _ = pending_rule(client, fake_llm)
    usage_rule.test_cases = PASSING
    usage_rule.save()

    review.retire_rule(usage_rule)

    assert not SentenceAnalysis.objects.filter(is_stale=True).exists()
    for transition in (review.approve_rule, review.retire_rule):
        with pytest.raises(review.Refused):
            transition(usage_rule)


def test_rule_retired_while_analyzing_is_not_saved_as_the_basis(client, fake_llm):
    place = rule(register_de(client, fake_llm, "장소"), "장소")
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}
    fake_llm.before_respond = lambda: review.retire_rule(place)

    response = analyze(client, TOKYO_DE)

    assert [item["name"] for item in response.json()["grammar"]] == ["장소"]
    assert not SpanMatch.objects.filter(rule=place).exists()
