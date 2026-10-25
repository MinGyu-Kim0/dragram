"""승인된 판별 규칙으로 구간을 LLM 없이 확정(#55, 구간 판정 절차 3단계)."""

import json

import pytest
from django.db import IntegrityError, transaction

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
from tests.analysis.test_colloquial import CHAU, MICHAU, TESHIMAU, linked, register

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
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "pos_tags": ["particle"],
            "function_tags": [],
            "function_tags_review_status": None,
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
    generations = (decided.generation, other.generation)
    version = patterns.pattern_set_version()

    review.retire_rule(place)

    place.refresh_from_db()
    assert place.status == UsageRule.Status.RETIRED
    decided.refresh_from_db()
    other.refresh_from_db()
    assert (decided.is_stale, other.is_stale) == (True, False)
    assert (decided.generation, other.generation) == (generations[0] + 1, generations[1])
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

    # 분석하는 사이 영향 범위가 바뀐 결과는 저장하지 않고 실패로 알린다(#98).
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not SpanMatch.objects.filter(rule=place).exists()


RULES = "/admin/analysis/usagerule/"


def rule_form(pattern, usage_name="장소", condition=AFTER_PLACE, cases=PASSING):
    return {
        "pattern": pattern.pk,
        "usage": pattern.usages.get(name=usage_name).pk,
        "condition": json.dumps(condition, ensure_ascii=False),
        "test_cases": json.dumps(cases, ensure_ascii=False),
    }


def test_admin_adds_a_pending_rule(admin_client, admin_user, client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")

    response = admin_client.post(f"{RULES}add/", rule_form(pattern))

    assert response.status_code == 302
    added = UsageRule.objects.get()
    assert (added.status, added.created_by, added.condition) == (
        UsageRule.Status.PENDING,
        admin_user,
        AFTER_PLACE,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"condition": "[]"},
        {"condition": json.dumps([{"position": 0}])},
        {"condition": json.dumps([{"position": -1, "pos4": "地名"}])},
        {"test_cases": json.dumps([{"text": "大阪で働く"}])},
        {"test_cases": json.dumps([{"text": "大阪で働く", "should_apply": "yes"}])},
        {"test_cases": json.dumps([{"text": "大阪で⟨N1⟩回働く", "should_apply": True}])},
    ],
)
def test_malformed_rule_is_not_saved(admin_client, client, fake_llm, changes):
    pattern = register_de(client, fake_llm, "장소")

    response = admin_client.post(f"{RULES}add/", {**rule_form(pattern), **changes})

    assert response.status_code == 200
    assert not UsageRule.objects.exists()


def test_usage_of_another_pattern_is_refused(admin_client, client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    fake_llm.response = {
        "translation_ko": "집에 간다",
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
    other = GrammarUsage.objects.get(name="도착점")

    response = admin_client.post(f"{RULES}add/", {**rule_form(pattern), "usage": other.pk})

    assert response.status_code == 200
    assert not UsageRule.objects.exists()


@pytest.mark.parametrize("status", [UsageRule.Status.APPROVED, UsageRule.Status.RETIRED])
def test_approved_or_retired_rule_cannot_be_edited_or_deleted(
    admin_client, client, fake_llm, status
):
    pattern = register_de(client, fake_llm, "장소")
    fixed = rule(pattern, "장소", status=status)

    admin_client.post(
        f"{RULES}{fixed.pk}/change/",
        rule_form(pattern, usage_name="수단", condition=[{"position": 1}]),
    )

    fixed.refresh_from_db()
    assert (fixed.usage.name, fixed.condition, fixed.status) == ("장소", AFTER_PLACE, status)
    assert admin_client.post(f"{RULES}{fixed.pk}/delete/").status_code == 403


def test_pending_rule_can_be_edited(admin_client, client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    draft = rule(pattern, "장소", status=UsageRule.Status.PENDING)

    response = admin_client.post(
        f"{RULES}{draft.pk}/change/", rule_form(pattern, condition=[{"position": 1}])
    )

    assert response.status_code == 302
    draft.refresh_from_db()
    assert (draft.condition, draft.test_cases) == ([{"position": 1}], PASSING)


def test_admin_actions_approve_and_retire_a_rule(admin_client, admin_user, client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    draft = rule(pattern, "장소", status=UsageRule.Status.PENDING)
    UsageRule.objects.filter(pk=draft.pk).update(test_cases=PASSING)

    admin_client.post(RULES, {"action": "approve", "_selected_action": [draft.pk]})
    draft.refresh_from_db()
    assert (draft.status, draft.approved_by) == (UsageRule.Status.APPROVED, admin_user)

    admin_client.post(RULES, {"action": "retire", "_selected_action": [draft.pk]})
    draft.refresh_from_db()
    assert draft.status == UsageRule.Status.RETIRED


@pytest.mark.parametrize("base_status", [ReviewStatus.APPROVED, ReviewStatus.PENDING])
def test_rule_of_a_linked_colloquial_pattern_points_at_a_base_usage(client, fake_llm, base_status):
    base, variant = linked(fake_llm)
    GrammarPattern.objects.update(status=ReviewStatus.APPROVED)
    GrammarUsage.objects.filter(pattern=base).update(status=ReviewStatus.APPROVED)
    GrammarPattern.objects.filter(pk=base.pk).update(status=base_status)
    # 규칙은 실제로 매칭된 회화체 패턴에 걸고, 용법은 원형의 것이다(design-decisions 42절).
    UsageRule.objects.create(
        pattern=variant,
        usage=base.usages.get(),
        condition=[{"position": -1, "lemma": "見る"}],
        status=UsageRule.Status.APPROVED,
    )
    fake_llm.forget_requests()
    fake_llm.response = {"translation_ko": "전부 봐 버렸다"}

    analyze(client, MICHAU)

    decided = base_status == ReviewStatus.APPROVED
    assert (asked_spans(fake_llm) == []) is decided
    assert SpanMatch.objects.filter(decided_by="rule").exists() is decided


def test_rule_is_stored_only_on_spans_decided_by_rule(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    place = rule(pattern, "장소")
    span = SpanMatch.objects.get()

    for decided_by in (None, "llm"):
        with pytest.raises(IntegrityError), transaction.atomic():
            SpanMatch.objects.filter(pk=span.pk).update(decided_by=decided_by, rule=place)


def test_rule_whose_pattern_changed_meanwhile_is_not_approved(client, fake_llm):
    usage_rule, pattern = pending_rule(client, fake_llm)
    UsageRule.objects.filter(pk=usage_rule.pk).update(test_cases=PASSING)
    fake_llm.response = {
        "translation_ko": "집에 간다",
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
    # 액션 목록을 연 뒤 다른 관리자가 규칙의 패턴을 바꿨다.
    UsageRule.objects.filter(pk=usage_rule.pk).update(pattern=GrammarPattern.objects.get(name="に"))

    with pytest.raises(review.Refused, match="그사이"):
        review.approve_rule(usage_rule)


def test_saving_a_rule_approved_meanwhile_reports_that_nothing_was_saved(
    admin_client, client, fake_llm
):
    pattern = register_de(client, fake_llm, "장소")
    draft = rule(pattern, "장소", status=UsageRule.Status.PENDING)
    form = rule_form(pattern, condition=[{"position": 1}])
    page = admin_client.get(f"{RULES}{draft.pk}/change/")
    assert page.status_code == 200
    UsageRule.objects.filter(pk=draft.pk).update(status=UsageRule.Status.APPROVED)

    response = admin_client.post(f"{RULES}{draft.pk}/change/", form, follow=True)

    draft.refresh_from_db()
    assert draft.condition == AFTER_PLACE
    assert "저장하지 않았습니다" in response.content.decode()


def test_merging_a_colloquial_usage_moves_its_rules_to_the_base_usage(fake_llm):
    base = register(fake_llm, "食べてしまった", TESHIMAU, "먹어 버렸다")
    variant = register(fake_llm, "食べちゃった", CHAU, "먹어 버렸다")
    own, done = variant.usages.get(), base.usages.get()
    own_rule = UsageRule.objects.create(
        pattern=variant, usage=own, condition=[{"position": -1, "pos1": "動詞"}]
    )

    # 합친 자기 용법은 지워지므로, 그 용법을 가리키던 규칙도 합칠 원형 용법을 가리킨다(#64).
    review.link_variant(variant, base, {own.pk: done.pk})

    own_rule.refresh_from_db()
    assert (own_rule.pattern, own_rule.usage) == (variant, done)


@pytest.mark.parametrize(
    "meanwhile",
    [
        lambda: GrammarUsage.objects.filter(name="장소").update(status=ReviewStatus.PENDING),
        lambda: GrammarPattern.objects.filter(name="で").update(status=ReviewStatus.PENDING),
    ],
    ids=["usage-unapproved", "pattern-unapproved"],
)
def test_rule_whose_knowledge_was_unapproved_while_analyzing_is_not_saved(
    client, fake_llm, meanwhile
):
    place = rule(register_de(client, fake_llm, "장소"), "장소")
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}
    fake_llm.before_respond = meanwhile

    analyze(client, TOKYO_DE)

    assert not SpanMatch.objects.filter(rule=place).exists()


def base_rule_ready(fake_llm):
    base, variant = linked(fake_llm)
    GrammarPattern.objects.update(status=ReviewStatus.APPROVED)
    GrammarUsage.objects.filter(pattern=base).update(status=ReviewStatus.APPROVED)
    return base, variant


def test_approving_a_rule_of_a_base_pattern_leaves_its_colloquial_analyses_alone(client, fake_llm):
    base, _ = base_rule_ready(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, MICHAU)
    colloquial = SentenceAnalysis.objects.get(translation_ko="전부 봐 버렸다")
    base_rule = UsageRule.objects.create(
        pattern=base,
        usage=base.usages.get(),
        condition=[{"position": -1, "lemma": "食べる"}],
        test_cases=[
            {"text": "パンを食べてしまう", "should_apply": True},
            {"text": "映画を見てしまう", "should_apply": False},
        ],
    )

    review.approve_rule(base_rule)

    colloquial.refresh_from_db()
    assert not colloquial.is_stale


def test_rule_whose_usage_left_the_pattern_is_not_approved(fake_llm):
    base, variant = base_rule_ready(fake_llm)
    pending = UsageRule.objects.create(
        pattern=variant,
        usage=base.usages.get(),
        condition=[{"position": -1, "pos1": "動詞"}],
        test_cases=[
            {"text": "全部食べちゃった", "should_apply": True},
            {"text": "ちゃう", "should_apply": False},
        ],
    )
    # 연결을 풀면 원형 용법은 더는 이 회화체의 후보가 아니다.
    review.unlink_variant(variant)

    with pytest.raises(review.Refused, match="용법"):
        review.approve_rule(pending)


def test_rule_approved_while_analyzing_keeps_the_result_from_being_saved(client, fake_llm):
    # 분석이 규칙을 미검수로 읽은 뒤 저장 전에 승인되면, 승인의 stale 처리가 저장 전 구간을
    # 보지 못해 새 규칙이 적용되지 않은 결과가 fresh로 남는다.
    pending = rule(register_de(client, fake_llm, "장소"), "장소", status=UsageRule.Status.PENDING)
    fake_llm.response = {"translation_ko": "도쿄에서 만난다", "spans": [span_answer(0, "usage", 1)]}
    fake_llm.before_respond = lambda: UsageRule.objects.filter(pk=pending.pk).update(
        status=UsageRule.Status.APPROVED
    )

    response = analyze(client, TOKYO_DE)

    # 분석하는 사이 영향 범위가 바뀐 결과는 저장하지 않고 실패로 알린다(#98).
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not SentenceAnalysis.objects.filter(translation_ko="도쿄에서 만난다").exists()


def test_rule_form_refuses_a_usage_merged_away_after_it_was_chosen(
    admin_client, fake_llm, monkeypatch
):
    base = register(fake_llm, "食べてしまった", TESHIMAU, "먹어 버렸다")
    variant = register(fake_llm, "食べちゃった", CHAU, "먹어 버렸다")
    own, done = variant.usages.get(), base.usages.get()
    lock_links = patterns.lock_links

    def merged_first(*args, **kwargs):
        # 폼이 용법을 고른 뒤, 검증이 잠금을 잡기 직전에 그 용법이 원형으로 합쳐졌다.
        monkeypatch.setattr(patterns, "lock_links", lock_links)
        review.link_variant(variant, base, {own.pk: done.pk})
        return lock_links(*args, **kwargs)

    monkeypatch.setattr(patterns, "lock_links", merged_first)
    form = {
        "pattern": variant.pk,
        "usage": own.pk,
        "condition": json.dumps([{"position": -1, "pos1": "動詞"}]),
        "test_cases": json.dumps([{"text": "全部食べちゃった", "should_apply": True}]),
    }

    response = admin_client.post(f"{RULES}add/", form)

    assert response.status_code == 200
    assert not UsageRule.objects.exists()


def test_approving_a_rule_of_a_usage_closed_pattern_leaves_its_analyses_alone(client, fake_llm):
    # 용법 완결 패턴의 구간은 2단계에서 먼저 확정되므로 새 규칙이 결과를 바꾸지 않는다.
    usage_rule, pattern = pending_rule(client, fake_llm)
    UsageRule.objects.filter(pk=usage_rule.pk).update(test_cases=PASSING)
    GrammarPattern.objects.filter(pk=pattern.pk).update(usage_closed=True)

    review.approve_rule(usage_rule)

    assert not SentenceAnalysis.objects.filter(is_stale=True).exists()


def test_rule_with_text_that_cannot_be_stored_is_refused_by_the_form(
    admin_client, client, fake_llm
):
    pattern = register_de(client, fake_llm, "장소")
    form = {**rule_form(pattern), "condition": '[{"position": -1, "lemma": "\\ud800"}]'}

    response = admin_client.post(f"{RULES}add/", form)

    assert response.status_code == 200
    assert not UsageRule.objects.exists()
