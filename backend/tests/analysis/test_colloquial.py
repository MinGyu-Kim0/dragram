"""회화체 패턴을 원형에 연결하기(#63)."""

import html
import threading
from unittest.mock import ANY

import pytest
from django.contrib.auth.models import Permission
from django.db import IntegrityError, connection, transaction
from django.db.models import F

from analysis import patterns, review
from analysis.admin import GrammarUsageAdmin
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternSetVersion,
    SentenceAnalysis,
    SpanMatch,
)
from tests.analysis.helpers import (
    analyze,
    connected_client,
    new_pattern,
    new_usage,
    pattern_form,
    span_answer,
    wait_until_blocked,
)

pytestmark = pytest.mark.django_db

PATTERNS = "/admin/analysis/grammarpattern/"
# 토큰: 0 食べ / 1 て / 2 しまっ / 3 た
TESHIMAU = new_pattern(
    (1, "lemma"),
    (2, "lemma"),
    pattern_name="てしまう",
    usage_name="완료",
    explanation_ko="동작이 끝나 버렸음을 나타낸다",
    example_ja="宿題を忘れてしまった",
)
# 토큰: 0 食べ / 1 ちゃっ / 2 た
CHAU = new_pattern(
    (1, "lemma"),
    pattern_name="ちゃう",
    usage_name="완료(회화체)",
    explanation_ko="てしまう의 회화체",
    example_ja="宿題を忘れちゃった",
)


def register(fake_llm, sentence, proposal, translation="번역"):
    """다른 문장을 분석해 새 패턴을 등록·활성화한다."""
    mine = fake_llm.response
    fake_llm.response = {"translation_ko": translation, "new_patterns": [proposal]}
    analyze(connected_client(), sentence)
    fake_llm.response = mine
    return GrammarPattern.objects.get(name=proposal["pattern_name"])


def version():
    return PatternSetVersion.objects.get().version


def base_and_variant(fake_llm):
    """원형 てしまう와, 자기 용법이 반려돼 연결할 수 있는 회화체 ちゃう."""
    base = register(fake_llm, "食べてしまった", TESHIMAU, "먹어 버렸다")
    variant = register(fake_llm, "食べちゃった", CHAU, "먹어 버렸다")
    review.reject_usage(variant.usages.get())
    return base, variant


def fresh(pattern):
    pattern.refresh_from_db()
    return pattern


def test_linking_points_the_variant_at_its_base_and_raises_the_version(fake_llm):
    base, variant = base_and_variant(fake_llm)
    before = version()

    review.link_variant(variant, base)

    variant = fresh(variant)
    assert (variant.variant_of, variant.register) == (base, "colloquial")
    # 자기 용법이 없어 매칭에서 빠져 있던 회화체가 원형의 용법으로 매칭 자격을 얻는다.
    assert version() == before + 1


def test_linking_makes_analyses_with_the_variant_stale(fake_llm):
    base, variant = base_and_variant(fake_llm)
    using = SentenceAnalysis.objects.get(
        translation_ko="먹어 버렸다", span_matches__pattern=variant
    )
    SentenceAnalysis.objects.filter(pk=using.pk).update(is_stale=False)
    generation = SentenceAnalysis.objects.get(pk=using.pk).generation

    review.link_variant(variant, base)

    using.refresh_from_db()
    assert (using.is_stale, using.generation) == (True, generation + 1)


# 연결 거부 조건. (base, variant, teru) → (연결할 패턴, 원형). teru는 용법이 반려된 다른 회화체다.
def self_link(base, variant, teru):
    return variant, variant


def base_is_a_variant(base, variant, teru):
    review.link_variant(teru, base)
    return variant, teru


def base_was_a_variant(base, variant, teru):
    # 연결했다가 해제한 회화체는 register가 회화체로 남아 원형이 될 수 없다.
    review.link_variant(teru, base)
    review.unlink_variant(teru)
    return variant, teru


def pattern_is_a_base(base, variant, teru):
    review.link_variant(teru, variant)
    return variant, base


def base_rejected(base, variant, teru):
    review.reject_pattern(base)
    return variant, base


def variant_rejected(base, variant, teru):
    review.reject_pattern(variant)
    return variant, base


def already_linked(base, variant, teru):
    review.link_variant(variant, base)
    return variant, base


def own_usage_left(base, variant, teru):
    review.unreject_usage(variant.usages.get())
    return variant, base


REFUSALS = [
    self_link,
    base_is_a_variant,
    base_was_a_variant,
    pattern_is_a_base,
    base_rejected,
    variant_rejected,
    already_linked,
    own_usage_left,
]


@pytest.mark.parametrize("case", REFUSALS)
def test_link_is_refused_and_changes_nothing(fake_llm, case):
    base, variant = base_and_variant(fake_llm)
    # 토큰: 0 見 / 1 てる
    teru = register(
        fake_llm,
        "見てる",
        new_pattern((1, "lemma"), pattern_name="てる", example_ja="本を読んでる"),
    )
    review.reject_usage(teru.usages.get())
    pattern, target = case(base, variant, teru)
    pattern = fresh(pattern)
    before = (version(), pattern.variant_of_id, pattern.register)

    with pytest.raises(review.Refused):
        review.link_variant(pattern, target)

    pattern = fresh(pattern)
    assert (version(), pattern.variant_of_id, pattern.register) == before


def test_sentence_cached_before_linking_gets_the_variant_span(client, fake_llm):
    base, variant = base_and_variant(fake_llm)
    # 회화체의 자기 용법이 반려돼 매칭되지 않을 때 캐시된 문장
    fake_llm.response = {"translation_ko": "전부 봐 버렸다"}
    analyze(client, "全部見ちゃった")

    review.link_variant(variant, base)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    response = analyze(client, "全部見ちゃった")

    [request] = fake_llm.rematch_requests
    assert [span["colloquial_of"] for span in request["spans"]] == ["てしまう"]
    assert [item["variant_of"] for item in response.json()["grammar"]] == ["てしまう"]


def test_unlinking_keeps_the_register_and_makes_analyses_stale(fake_llm):
    base, variant = base_and_variant(fake_llm)
    review.link_variant(variant, base)
    SentenceAnalysis.objects.update(is_stale=False)
    before = version()

    review.unlink_variant(variant)

    variant = fresh(variant)
    assert (variant.variant_of, variant.register) == (None, "colloquial")
    # 자격을 잃는 쪽이라 버전은 올리지 않는다.
    assert version() == before
    using = SentenceAnalysis.objects.get(span_matches__pattern=variant)
    assert using.is_stale


def test_unlinking_a_pattern_that_is_not_linked_is_refused(fake_llm):
    _, variant = base_and_variant(fake_llm)

    with pytest.raises(review.Refused):
        review.unlink_variant(variant)


def test_variant_cannot_point_at_itself_or_be_standard(fake_llm):
    base, variant = base_and_variant(fake_llm)

    with pytest.raises(IntegrityError), transaction.atomic():
        GrammarPattern.objects.filter(pk=variant.pk).update(
            variant_of=F("id"), register="colloquial"
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        GrammarPattern.objects.filter(pk=variant.pk).update(variant_of=base, register="standard")


def act(admin_client, action, *objects, **data):
    return admin_client.post(
        PATTERNS,
        {"action": action, "_selected_action": [obj.pk for obj in objects], **data},
        follow=True,
    )


def test_variant_is_linked_and_unlinked_with_admin_actions(admin_client, fake_llm):
    base, variant = base_and_variant(fake_llm)

    act(admin_client, "link_variant", variant, base_pattern_id=str(base.pk))
    assert fresh(variant).variant_of == base

    act(admin_client, "unlink_variant", variant)
    assert fresh(variant).variant_of is None


@pytest.mark.parametrize("base_pattern_id", ["", "abc", "999999"])
def test_link_action_without_a_valid_base_shows_the_reason(admin_client, fake_llm, base_pattern_id):
    _, variant = base_and_variant(fake_llm)

    response = act(admin_client, "link_variant", variant, base_pattern_id=base_pattern_id)

    assert fresh(variant).variant_of is None
    assert "원형 패턴 ID" in html.unescape(response.content.decode())


def linked(fake_llm):
    base, variant = base_and_variant(fake_llm)
    review.link_variant(variant, base)
    return fresh(base), fresh(variant)


# 토큰: 0 全部 / 1 見 / 2 ちゃっ / 3 た
MICHAU = "全部見ちゃった"
CHAU_ITEM = {
    "start": 3,
    "end": 6,
    "state": "decided",
    "connection": ANY,
    "pattern_name": "ちゃう",
    "name": "완료",
    "explanation_ko": "동작이 끝나 버렸음을 나타낸다",
    "korean_equivalent": None,
    "korean_equivalent_review_status": None,
    "pos_tags": ["auxiliary_verb"],
    "function_tags": [],
    "function_tags_review_status": None,
    "review_status": "pending",
    "register": "colloquial",
    "variant_of": "てしまう",
}


def test_linked_variant_span_uses_the_base_usage_and_shows_colloquial(client, fake_llm):
    linked(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, MICHAU)

    [span] = fake_llm.requests[-1]["spans"]
    assert span["colloquial_of"] == "てしまう"
    assert span["candidates"] == [
        {"candidate_id": 1, "name": "완료", "explanation_ko": "동작이 끝나 버렸음을 나타낸다"}
    ]
    assert response.json()["grammar"] == [CHAU_ITEM]


def test_checking_variant_span_carries_the_base_usage_and_colloquial(client, fake_llm):
    # 후보가 원형 용법 하나라 판정 전에도 그 칸을 싣는다(#203).
    linked(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, MICHAU)

    [checking] = response.events[0]["checking"]
    assert checking["usage"] == {
        k: v for k, v in CHAU_ITEM.items() if k not in ("start", "end", "state")
    }


def test_standard_span_has_no_colloquial_fields_set(client, fake_llm):
    base, _ = linked(fake_llm)
    fake_llm.response = {"translation_ko": "다 먹어 버렸다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, "全部食べてしまった")

    [item] = response.json()["grammar"]
    assert (item["register"], item["variant_of"]) == ("standard", None)
    assert "colloquial_of" not in fake_llm.requests[-1]["spans"][0]


def test_variant_span_disappears_when_the_base_is_rejected(client, fake_llm):
    base, _ = linked(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, MICHAU)
    review.reject_pattern(base)
    # 재분석 전에도 반려된 원형의 회화체 구간은 보이지 않는다.
    SentenceAnalysis.objects.update(is_stale=False)

    response = analyze(client, MICHAU)

    assert response.json()["grammar"] == []


@pytest.mark.parametrize(("base_status", "shown"), [("pending", "pending"), ("rejected", None)])
def test_unresolved_variant_span_follows_the_base_status(client, fake_llm, base_status, shown):
    base, variant = linked(fake_llm)
    GrammarPattern.objects.filter(pk=variant.pk).update(status="approved")
    fake_llm.response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [span_answer(0, "unresolved")],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [span_answer(0, "unresolved")],
    }
    analyze(client, MICHAU)
    GrammarPattern.objects.filter(pk=base.pk).update(status=base_status)

    response = analyze(client, MICHAU)

    statuses = [item["review_status"] for item in response.json()["grammar"]]
    assert statuses == ([] if shown is None else [shown])


def test_span_whose_usage_left_the_family_is_hidden_before_reanalysis(client, fake_llm):
    _, variant = linked(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, MICHAU)

    review.unlink_variant(variant)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다"}
    response = analyze(client, MICHAU)

    # 재분석하는 동안 먼저 보이는 옛 결과에서 원형 용법을 쓰던 구간이 빠진다.
    assert response.events[0]["type"] == "previous"
    assert response.events[0]["grammar"] == []


@pytest.mark.parametrize(
    ("example_ja", "stored"),
    [("本を忘れてしまった", "本を忘れてしまった"), ("本を忘れちゃった", None)],
)
def test_new_usage_of_a_variant_span_is_added_under_the_base(client, fake_llm, example_ja, stored):
    base, variant = linked(fake_llm)
    fake_llm.response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [
            span_answer(
                0, "unfound", new_usage=new_usage("유감", "아쉬운 마음을 담는다", example_ja)
            )
        ],
    }

    response = analyze(client, MICHAU)

    usage = GrammarUsage.objects.get(name="유감")
    # 예문은 원형 조건으로 검사한다. 회화체 형태로 쓴 예문은 원형에 걸리지 않아 버린다.
    assert (usage.pattern, usage.example_ja) == (base, stored)
    assert [item["name"] for item in response.json()["grammar"]] == ["유감"]


def test_new_usage_is_not_added_when_the_link_changed_meanwhile(client, fake_llm):
    _, variant = linked(fake_llm)
    fake_llm.response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [
            span_answer(
                0,
                "unfound",
                new_usage=new_usage("유감", "아쉬운 마음을 담는다", "本を忘れてしまった"),
            )
        ],
    }
    fake_llm.before_respond = lambda: review.unlink_variant(variant)

    analyze(client, MICHAU)

    assert not GrammarUsage.objects.filter(name="유감").exists()


CASES = [
    {"text": "宿題を忘れてしまった", "should_match": True},
    {"text": "宿題を忘れた", "should_match": False},
]
VARIANT_CASES = [
    {"text": "宿題を忘れちゃった", "should_match": True},
    {"text": "宿題を忘れた", "should_match": False},
]


def approved(pattern, cases):
    review.update_test_cases(pattern, cases)
    review.approve_pattern(pattern)
    return fresh(pattern)


def closed_variant(fake_llm):
    """승인된 원형(승인된 용법 하나)에 연결된, 승인·용법 완결 회화체."""
    base, variant = linked(fake_llm)
    base = approved(base, CASES)
    review.approve_usage(base.usages.get())
    variant = approved(variant, VARIANT_CASES)
    review.close_usages(variant)
    return fresh(base), fresh(variant)


def test_variant_is_closed_only_with_an_approved_base(fake_llm):
    base, variant = linked(fake_llm)
    review.approve_usage(base.usages.get())
    variant = approved(variant, VARIANT_CASES)

    with pytest.raises(review.Refused):
        review.close_usages(variant)

    approved(base, CASES)
    review.close_usages(variant)
    assert fresh(variant).usage_closed


def test_closed_variant_span_is_decided_without_llm_only_while_the_base_is_approved(
    client, fake_llm
):
    base, _ = closed_variant(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다"}
    analyze(client, MICHAU)
    assert fake_llm.requests[-1]["spans"] == []

    # 원형만 미검수가 되어도(사건 연쇄를 거치지 않은 경우까지) LLM 없이 정하지 않는다.
    GrammarPattern.objects.filter(pk=base.pk).update(status="pending")
    analyze(client, "全部読んじゃった")
    assert len(fake_llm.requests[-1]["spans"]) == 1


def base_events():
    def add_usage(base):
        with transaction.atomic():
            patterns.add_usage(base, "유감", "아쉬움", None)

    return {
        "용법 추가": add_usage,
        "용법 반려": lambda base: review.reject_usage(base.usages.get()),
        "용법 승인 취소": lambda base: review.unapprove_usage(base.usages.get()),
        "패턴 반려": review.reject_pattern,
        "패턴 승인 취소": review.unapprove_pattern,
    }


@pytest.mark.parametrize("event", base_events().values(), ids=base_events().keys())
def test_base_events_open_the_variant_and_make_its_analyses_stale(client, fake_llm, event):
    base, variant = closed_variant(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다"}
    analyze(client, MICHAU)
    SentenceAnalysis.objects.update(is_stale=False)

    event(base)

    assert not fresh(variant).usage_closed
    assert SentenceAnalysis.objects.get(translation_ko="전부 봐 버렸다").is_stale


@pytest.mark.parametrize(
    "event",
    [review.reject_pattern, review.unapprove_pattern, "unreject"],
)
def test_base_pattern_events_reach_analyses_of_its_variants(client, fake_llm, event):
    base, _ = linked(fake_llm)
    base = approved(base, CASES)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, MICHAU)
    if event == "unreject":
        review.reject_pattern(base)
        event = review.unreject_pattern
    SentenceAnalysis.objects.update(is_stale=False)

    event(fresh(base))

    assert SentenceAnalysis.objects.get(translation_ko="전부 봐 버렸다").is_stale


def test_unrejected_base_usage_makes_analyses_of_its_variants_stale(client, fake_llm):
    base, _ = linked(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, MICHAU)
    usage = base.usages.get()
    review.reject_usage(usage)
    SentenceAnalysis.objects.update(is_stale=False)

    review.unreject_usage(usage)

    assert SentenceAnalysis.objects.get(translation_ko="전부 봐 버렸다").is_stale


@pytest.mark.parametrize(
    ("base_approved", "variant_approved", "shown"),
    [(False, True, "pending"), (True, False, "pending"), (True, True, "approved")],
    ids=["원형만 미검수", "회화체만 미검수", "둘 다 승인"],
)
def test_variant_span_is_approved_only_when_both_patterns_are_approved(
    client, fake_llm, base_approved, variant_approved, shown
):
    base, variant = linked(fake_llm)
    review.approve_usage(base.usages.get())
    if base_approved:
        approved(base, CASES)
    if variant_approved:
        approved(variant, VARIANT_CASES)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, MICHAU)

    [item] = response.json()["grammar"]
    assert (item["state"], item["review_status"]) == ("decided", shown)


def test_unrejecting_the_base_raises_the_version_for_its_variants(fake_llm):
    base, _ = linked(fake_llm)
    # 활성화 근거가 없어 반려 취소 뒤에도 원형은 비활성이다. 회화체는 원형의 용법으로 다시
    # 매칭 자격을 얻는다.
    GrammarPattern.objects.filter(pk=base.pk).update(test_cases=[])
    review.reject_pattern(base)
    before = version()

    review.unreject_pattern(fresh(base))

    assert not fresh(base).is_active
    assert version() == before + 1


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_unlinking_while_an_analysis_adds_a_base_usage_does_not_deadlock(fake_llm, monkeypatch):
    # 용법 완결 회화체에 연결된 원형 てしまう 구간에 분석이 새 용법을 더한다. 새 용법은 원형을
    # 잠근 뒤 회화체의 용법 완결을 뗀다. 그사이 관리자가 연결을 푼다.
    _, variant = closed_variant(fake_llm)
    result = {}
    matchable_family = patterns.matchable_family

    def unlink():
        try:
            review.unlink_variant(variant)
            result["unlinked"] = True
        finally:
            connection.close()

    def unlink_meanwhile(pattern):
        # 분석이 원형을 잠근 채 회화체를 바꾸기 직전에 연결 해제가 시작되게 한다.
        monkeypatch.setattr(patterns, "matchable_family", matchable_family)
        thread = threading.Thread(target=unlink)
        thread.start()
        wait_until_blocked()
        result["thread"] = thread
        return matchable_family(pattern)

    monkeypatch.setattr(patterns, "matchable_family", unlink_meanwhile)
    fake_llm.response = {
        "translation_ko": "다 먹어 버렸다",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage("유감", "아쉬움", "本を忘れてしまった"))
        ],
    }

    response = analyze(connected_client(), "全部食べてしまった")
    result["thread"].join()

    assert "error" not in response.json()
    assert result.get("unlinked")
    assert fresh(variant).variant_of is None


def test_own_usage_of_a_linked_variant_cannot_be_unrejected(fake_llm):
    _, variant = linked(fake_llm)

    with pytest.raises(review.Refused):
        review.unreject_usage(variant.usages.get())

    assert variant.usages.get().status == "rejected"


def test_analysis_is_not_saved_when_the_variant_is_unlinked_meanwhile(client, fake_llm):
    _, variant = linked(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    # 원형 용법을 고른 회화체 구간이 연결이 풀린 뒤 저장되면 소속이 어긋난 채 fresh로 남는다.
    fake_llm.before_respond = lambda: review.unlink_variant(variant)

    response = analyze(client, MICHAU)

    # 분석하는 사이 영향 범위가 바뀐 결과는 저장하지 않고 실패로 알린다(#98).
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not SentenceAnalysis.objects.filter(translation_ko="전부 봐 버렸다").exists()


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_linking_while_an_analysis_adds_usages_to_both_patterns_does_not_deadlock(
    fake_llm, monkeypatch
):
    # 연결되지 않은 ちゃう와 てしまう(둘 다 자기 용법 있음)가 한 문장에 걸리고, 분석이 두 패턴에
    # 새 용법을 더하는 사이 관리자가 둘을 연결한다. 분석이 먼저 새 용법을 더한 패턴을 다른
    # 패턴에 연결해, 연결이 원형을 먼저 잠그면 분석과 서로 엇갈리게 한다.
    chosen = [
        register(fake_llm, "食べてしまった", TESHIMAU, "먹어 버렸다"),
        register(fake_llm, "食べちゃった", CHAU, "먹어 버렸다"),
    ]
    result = {}
    matchable_family = patterns.matchable_family

    def link(variant, base):
        try:
            review.link_variant(variant, base)
            result["link"] = "linked"
        except review.Refused:
            result["link"] = "refused"
        finally:
            connection.close()

    def link_meanwhile(pattern):
        monkeypatch.setattr(patterns, "matchable_family", matchable_family)
        [other] = [p for p in chosen if p.pk != pattern.pk]
        thread = threading.Thread(target=link, args=(pattern, other))
        thread.start()
        wait_until_blocked()
        result["thread"] = thread
        return matchable_family(pattern)

    monkeypatch.setattr(patterns, "matchable_family", link_meanwhile)
    # 토큰: 0 見 / 1 ちゃっ / 2 て / 3 忘れ / 4 て / 5 しまっ / 6 た
    fake_llm.response = {
        "translation_ko": "봐 버리고 잊어 버렸다",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage("유감", "아쉬움", "本を忘れちゃった")),
            span_answer(1, "unfound", new_usage=new_usage("유감", "아쉬움", "本を忘れてしまった")),
        ],
    }

    response = analyze(connected_client(), "見ちゃって忘れてしまった")
    result["thread"].join()

    assert "error" not in response.json()
    # 연결할 패턴에 자기 용법이 있어 연결은 거부된다.
    assert result["link"] == "refused"


def test_example_spreading_the_colloquial_form_into_the_base_still_counts_as_copying(
    client, fake_llm
):
    # 원문의 ちゃっ 한 토큰을 예문이 て·しまっ 두 토큰으로 펼쳐도, 문법 앞뒤로 이어 베낀 글자
    # (図書館で見 +
    # た本だ = 8자)는 한 번의 복사로 센다.
    linked(fake_llm)
    # 토큰: 0 図書館 / 1 で / 2 見 / 3 ちゃっ / 4 た / 5 本 / 6 だ
    fake_llm.response = {
        "translation_ko": "도서관에서 봐 버린 책이다",
        "spans": [
            span_answer(
                0, "unfound", new_usage=new_usage("유감", "아쉬움", "図書館で見てしまった本だ")
            )
        ],
    }
    fake_llm.rewrite_response = {
        "examples": [{"example_id": 0, "example_ja": "本を忘れてしまった"}]
    }

    analyze(client, "図書館で見ちゃった本だ")

    assert len(fake_llm.rewrite_requests) == 1
    assert GrammarUsage.objects.get(name="유감").example_ja == "本を忘れてしまった"


def test_unresolved_variant_span_is_not_saved_when_the_variant_is_unlinked_meanwhile(
    client, fake_llm
):
    _, variant = linked(fake_llm)
    fake_llm.response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [span_answer(0, "unresolved")],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [span_answer(0, "unresolved")],
    }
    fake_llm.before_respond = lambda: review.unlink_variant(variant)

    analyze(client, MICHAU)

    assert not SentenceAnalysis.objects.filter(translation_ko="전부 봐 버렸다").exists()


def test_variants_of_one_base_share_the_new_usage_added_in_one_sentence(client, fake_llm):
    base, _ = linked(fake_llm)
    # 토큰: 0 食べ / 1 ちまっ / 2 た
    chimau = register(
        fake_llm,
        "食べちまった",
        new_pattern((1, "lemma"), pattern_name="ちまう", example_ja="全部見ちまった"),
    )
    review.reject_usage(chimau.usages.get())
    review.link_variant(chimau, base)
    # 토큰: 0 見 / 1 ちゃっ / 2 て / 3 食べ / 4 ちまっ / 5 た
    fake_llm.response = {
        "translation_ko": "봐 버리고 먹어 버렸다",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage("유감", "아쉬움", "本を忘れてしまった")),
            span_answer(1, "unfound", new_usage=new_usage("유감", "아쉬움", "本を忘れてしまった")),
        ],
    }

    response = analyze(client, "見ちゃって食べちまった")

    assert [item["name"] for item in response.json()["grammar"]] == ["유감", "유감"]
    assert GrammarUsage.objects.filter(name="유감", pattern=base).count() == 1


def test_any_token_inside_a_variant_span_still_counts_as_copying(client, fake_llm):
    # 원형 が〜〜ね(아무거나 두 토큰)에 회화체 が〜ね(아무거나 한 토큰)를 연결한다. 회화체 구간의
    # 아무거나 자리(インターナショナル, 9자)를 예문이 그대로 옮기면 복사로 센다.
    # 토큰: 0 猫 / 1 が / 2 好き / 3 だ / 4 ね
    base = register(
        fake_llm,
        "猫が好きだね",
        new_pattern(
            (1, "lemma"),
            (2, "any"),
            (3, "any"),
            (4, "lemma"),
            pattern_name="が〜〜ね",
            example_ja="犬が元気だね",
        ),
    )
    # 토큰: 0 雨 / 1 が / 2 降る / 3 ね
    variant = register(
        fake_llm,
        "雨が降るね",
        new_pattern(
            (1, "lemma"), (2, "any"), (3, "lemma"), pattern_name="が〜ね", example_ja="花が咲くね"
        ),
    )
    review.reject_usage(variant.usages.get())
    review.link_variant(variant, base)
    # 토큰: 0 君 / 1 が / 2 インターナショナル / 3 ね
    fake_llm.response = {
        "translation_ko": "너는 국제적이네",
        "spans": [
            span_answer(
                0,
                "unfound",
                new_usage=new_usage("감탄", "감탄을 나타낸다", "猫がインターナショナルだね"),
            )
        ],
    }
    fake_llm.rewrite_response = {"examples": [{"example_id": 0, "example_ja": "犬が元気だね"}]}

    analyze(client, "君がインターナショナルね")

    assert len(fake_llm.rewrite_requests) == 1
    assert GrammarUsage.objects.get(name="감탄").example_ja == "犬が元気だね"


def test_analysis_is_not_saved_when_a_new_base_usage_opens_a_closed_span(client, fake_llm):
    # 용법 완결 ちゃう 구간은 LLM 없이 정해지는데, 같은 원형의 열린 ちまう 구간이 원형에 새 용법을
    # 더하면 그 용법 완결이 풀린다. 풀리기 전 기준의 확정 구간을 fresh로 저장하지 않는다.
    base, _ = closed_variant(fake_llm)
    chimau = register(
        fake_llm,
        "食べちまった",
        new_pattern((1, "lemma"), pattern_name="ちまう", example_ja="全部見ちまった"),
    )
    review.reject_usage(chimau.usages.get())
    review.link_variant(chimau, base)
    # 토큰: 0 見 / 1 ちゃっ / 2 て / 3 食べ / 4 ちまっ / 5 た
    fake_llm.response = {
        "translation_ko": "봐 버리고 먹어 버렸다",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage("유감", "아쉬움", "本を忘れてしまった"))
        ],
    }

    response = analyze(client, "見ちゃって食べちまった")

    assert fake_llm.requests[-1]["decided_spans"][0]["start_token_id"] == 1
    # 분석하는 사이 영향 범위가 바뀐 결과는 저장하지 않고 실패로 알린다(#98).
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not SentenceAnalysis.objects.filter(translation_ko="봐 버리고 먹어 버렸다").exists()


# 자기 용법이 남은 회화체를 연결하며 용법을 합치거나 옮기기(#64)


def with_own_usage(fake_llm):
    """원형 てしまう(용법 완료)와, 자기 용법 완료(회화체)가 남은 회화체 ちゃう."""
    base = register(fake_llm, "食べてしまった", TESHIMAU, "먹어 버렸다")
    variant = register(fake_llm, "食べちゃった", CHAU, "먹어 버렸다")
    return base, variant, base.usages.get(), variant.usages.get()


def test_merging_points_the_spans_at_the_base_usage_and_drops_the_own_usage(client, fake_llm):
    base, variant, done, own = with_own_usage(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, MICHAU)

    review.link_variant(variant, base, {own.pk: done.pk})

    assert not GrammarUsage.objects.filter(pk=own.pk).exists()
    span = SpanMatch.objects.get(analysis__translation_ko="전부 봐 버렸다")
    assert span.usage_id == done.pk
    assert span.candidates == [{"candidate_id": 1, "usage_id": done.pk}]


def divergent_variant_span(client, fake_llm, variant):
    """회화체 구간이 자기 용법 둘(후보 1 주 용법, 후보 2 대안)로 해석이 갈린 분석. 둘째 용법
    유감을 돌려준다."""
    with transaction.atomic():
        regret, _ = patterns.add_usage(variant, "유감", "아쉬운 마음을 담는다", None)
    fake_llm.response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [span_answer(0, "divergent", 1)],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "전부 봐 버렸다",
        "spans": [
            {
                **span_answer(0, "divergent", 1),
                "alternatives": [
                    {
                        "candidate_id": 2,
                        "translation_ko": "아쉽게도 전부 봐 버렸다",
                        "basis": "아쉬워하는 앞 문맥",
                    }
                ],
            }
        ],
    }
    analyze(client, MICHAU)
    return regret


def test_merged_duplicates_fold_and_a_divergent_span_left_without_alternatives_is_decided(
    client, fake_llm
):
    base, variant, done, own = with_own_usage(fake_llm)
    regret = divergent_variant_span(client, fake_llm, variant)

    review.link_variant(variant, base, {own.pk: done.pk, regret.pk: done.pk})

    span = SpanMatch.objects.get(analysis__translation_ko="전부 봐 버렸다")
    assert (span.state, span.usage_id, span.alternatives) == ("decided", done.pk, None)
    assert span.candidates == [{"candidate_id": 1, "usage_id": done.pk}]


@pytest.mark.parametrize(
    ("example_ja", "stored"),
    [("本を忘れてしまった", "本を忘れてしまった"), ("本を忘れちゃった", None)],
)
def test_moved_usage_joins_the_base_and_keeps_its_status(fake_llm, example_ja, stored):
    base, variant, _, own = with_own_usage(fake_llm)
    GrammarUsage.objects.filter(pk=own.pk).update(status="approved", example_ja=example_ja)

    review.link_variant(variant, base, {own.pk: None})

    own.refresh_from_db()
    # 회화체 형태로 쓴 예문은 원형 조건에 걸리지 않아 비운다.
    assert (own.pattern, own.status, own.example_ja) == (base, "approved", stored)


@pytest.mark.parametrize(
    ("base_usage_rejected", "reason"), [(False, "합침을 고릅니다"), (True, "반려 취소")]
)
def test_moving_a_usage_named_like_a_base_usage_is_refused_and_changes_nothing(
    fake_llm, base_usage_rejected, reason
):
    base, variant, done, own = with_own_usage(fake_llm)
    # 반려된 원형 용법과 이름이 같아도 옮기지 않는다(이름은 패턴 안에서 유일하다). 반려된 용법으로는
    # 합칠 수도 없어, 다른 길을 알려 준다.
    if base_usage_rejected:
        review.reject_usage(done)
    GrammarUsage.objects.filter(pk=own.pk).update(name="완료")

    with pytest.raises(review.Refused, match=reason):
        review.link_variant(variant, base, {own.pk: None})

    own.refresh_from_db()
    assert (own.pattern, fresh(variant).variant_of) == (variant, None)


def test_moving_into_a_base_without_open_usages_raises_the_version(fake_llm):
    base, variant, done, own = with_own_usage(fake_llm)
    # 원형은 반려되지 않은 용법이 없어 매칭에서 빠져 있다. 옮긴 용법으로 자격을 얻는다.
    review.reject_usage(done)
    before = version()

    review.link_variant(variant, base, {own.pk: None})

    assert version() == before + 1


def test_moving_opens_the_base_and_its_linked_variants(fake_llm):
    base, chau = closed_variant(fake_llm)
    review.close_usages(base)
    chimau = register(
        fake_llm,
        "食べちまった",
        new_pattern((1, "lemma"), pattern_name="ちまう", example_ja="全部見ちまった"),
    )

    review.link_variant(chimau, base, {chimau.usages.get().pk: None})

    # 원형에 용법을 더한 것과 같다. 원형의 용법이 둘이 되어 용법 완결이 아니다.
    assert (fresh(base).usage_closed, fresh(chau).usage_closed) == (False, False)


def generations():
    return dict(SentenceAnalysis.objects.values_list("translation_ko", "generation"))


@pytest.mark.parametrize("moved", [False, True], ids=["합침", "옮김"])
def test_merging_makes_analyses_of_the_base_and_its_variants_stale(fake_llm, moved):
    base = register(fake_llm, "食べてしまった", TESHIMAU, "먹어 버렸다")
    variant = register(fake_llm, "食べちゃった", CHAU, "먹어 치웠다")
    own = variant.usages.get()
    SentenceAnalysis.objects.update(is_stale=False)
    before = generations()

    review.link_variant(variant, base, {own.pk: None if moved else base.usages.get().pk})

    # 한 사건에서 여러 번 오를 수 있어 올랐는지만 본다.
    after = generations()
    assert all(after[translation] > n for translation, n in before.items())
    assert not SentenceAnalysis.objects.filter(is_stale=False).exists()


def test_moving_makes_other_analyses_referring_to_the_usage_stale(client, fake_llm):
    base = register(fake_llm, "食べてしまった", TESHIMAU, "먹어 버렸다")
    chau = register(fake_llm, "食べちゃった", CHAU, "먹어 치웠다")
    own = chau.usages.get()
    # ちまう를 ちゃう에 연결했다가 푼다. 재분석 전까지 ちまう 구간은 ちゃう의 용법을 가리킨다.
    chimau = register(
        fake_llm,
        "食べちまった",
        new_pattern((1, "lemma"), pattern_name="ちまう", example_ja="全部見ちまった"),
    )
    review.reject_usage(chimau.usages.get())
    review.link_variant(chimau, chau)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, "全部見ちまった")
    review.unlink_variant(chimau)
    before = generations()["전부 봐 버렸다"]

    review.link_variant(chau, base, {own.pk: None})

    assert generations()["전부 봐 버렸다"] > before


@pytest.mark.parametrize("moved", [False, True], ids=["합침", "옮김"])
def test_analysis_started_before_merging_is_not_saved(client, fake_llm, moved):
    base, variant, done, own = with_own_usage(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    # 회화체의 자기 용법을 고른 사이 관리자가 그 용법을 원형으로 합치거나 옮기며 연결한다.
    fake_llm.before_respond = lambda: review.link_variant(
        variant, base, {own.pk: None if moved else done.pk}
    )

    response = analyze(client, MICHAU)

    # 분석하는 사이 영향 범위가 바뀐 결과는 저장하지 않고 실패로 알린다(#98).
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not SentenceAnalysis.objects.filter(translation_ko="전부 봐 버렸다").exists()


# 대응표 거부 조건. (원형 용법 완료, 자기 용법 완료(회화체), 자기 용법 유감) → 대응표
def one_usage_left_out(done, own, regret):
    return {own.pk: done.pk}


def not_an_own_usage(done, own, regret):
    return {own.pk: done.pk, regret.pk: None, done.pk: None}


def target_is_not_a_base_usage(done, own, regret):
    return {own.pk: regret.pk, regret.pk: None}


def target_is_rejected(done, own, regret):
    review.reject_usage(done)
    return {own.pk: done.pk, regret.pk: None}


@pytest.mark.parametrize(
    "case",
    [one_usage_left_out, not_an_own_usage, target_is_not_a_base_usage, target_is_rejected],
)
def test_mapping_must_cover_the_own_usages_with_open_base_usages(fake_llm, case):
    base, variant, done, own = with_own_usage(fake_llm)
    with transaction.atomic():
        regret, _ = patterns.add_usage(variant, "유감", "아쉬운 마음을 담는다", None)
    mapping = case(done, own, regret)

    with pytest.raises(review.Refused):
        review.link_variant(variant, base, mapping)

    assert fresh(variant).variant_of is None
    assert set(variant.usages.values_list("pk", flat=True)) == {own.pk, regret.pk}


def test_rejected_own_usage_stays_with_the_variant_and_stays_hidden(client, fake_llm):
    base, variant, done, own = with_own_usage(fake_llm)
    fake_llm.response = {"translation_ko": "전부 봐 버렸다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, MICHAU)
    review.reject_usage(own)
    with transaction.atomic():
        regret, _ = patterns.add_usage(variant, "유감", "아쉬운 마음을 담는다", None)

    review.link_variant(variant, base, {regret.pk: done.pk})

    assert GrammarUsage.objects.get(pk=own.pk).pattern == variant
    SentenceAnalysis.objects.update(is_stale=False)
    response = analyze(client, MICHAU)
    assert response.json()["grammar"] == []


def test_link_action_asks_what_to_do_with_each_own_usage(admin_client, fake_llm):
    base, variant, done, own = with_own_usage(fake_llm)
    with transaction.atomic():
        regret, _ = patterns.add_usage(variant, "유감", "아쉬운 마음을 담는다", None)

    page = act(admin_client, "link_variant", variant, base_pattern_id=str(base.pk))

    assert fresh(variant).variant_of is None
    text = html.unescape(page.content.decode())
    assert "완료(회화체)" in text
    assert f'name="usage_{own.pk}"' in text
    # 합칠 원형 용법의 검수 상태도 보인다. 합치면 그 상태를 쓴다.
    assert f'<option value="{done.pk}">합침: 「완료」(Pending)</option>' in text
    assert 'name="csrfmiddlewaretoken"' in text
    # 원문(그 패턴을 등록한 문장)은 보이지 않는다.
    assert "食べちゃった" not in text

    act(
        admin_client,
        "link_variant",
        variant,
        base_pattern_id=str(base.pk),
        apply="1",
        **{f"usage_{own.pk}": str(done.pk), f"usage_{regret.pk}": "move"},
    )

    assert fresh(variant).variant_of == base
    assert not GrammarUsage.objects.filter(pk=own.pk).exists()
    assert GrammarUsage.objects.get(pk=regret.pk).pattern == base


def test_link_action_without_a_choice_for_every_usage_shows_the_reason(admin_client, fake_llm):
    base, variant, _, own = with_own_usage(fake_llm)

    response = act(
        admin_client,
        "link_variant",
        variant,
        base_pattern_id=str(base.pk),
        apply="1",
        **{f"usage_{own.pk}": ""},
    )

    assert fresh(variant).variant_of is None
    assert "골라야" in html.unescape(response.content.decode())


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_merging_while_an_analysis_adds_a_base_usage_does_not_deadlock(fake_llm, monkeypatch):
    # 분석이 원형 てしまう 구간에 새 용법을 더하며 원형을 잠근 사이, 관리자가 자기 용법이 남은
    # ちゃう를 연결하며 그 용법을 원형 용법으로 합친다.
    base, variant, done, own = with_own_usage(fake_llm)
    result = {}
    matchable_family = patterns.matchable_family

    def link():
        try:
            review.link_variant(variant, base, {own.pk: done.pk})
            result["linked"] = True
        finally:
            connection.close()

    def link_meanwhile(pattern):
        monkeypatch.setattr(patterns, "matchable_family", matchable_family)
        thread = threading.Thread(target=link)
        thread.start()
        wait_until_blocked()
        result["thread"] = thread
        return matchable_family(pattern)

    monkeypatch.setattr(patterns, "matchable_family", link_meanwhile)
    fake_llm.response = {
        "translation_ko": "다 먹어 버렸다",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage("유감", "아쉬움", "本を忘れてしまった"))
        ],
    }

    response = analyze(connected_client(), "全部食べてしまった")
    result["thread"].join()

    assert "error" not in response.json()
    assert result.get("linked")
    assert not GrammarUsage.objects.filter(pk=own.pk).exists()
    assert GrammarUsage.objects.filter(pattern=base, name="유감").exists()


# 토큰: 0 本 / 1 を / 2 読む
WO = new_pattern((1, "lemma"), pattern_name="を", usage_name="목적어", example_ja="水を飲む")


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_merging_while_another_pattern_event_locks_the_same_analyses_does_not_deadlock(
    client, fake_llm, monkeypatch
):
    # 원형 구간과 を 구간이 있는 분석(앞 id), 회화체 구간과 を 구간이 있는 분석(뒤 id)이 있다.
    # 연결·병합이 분석 행을 잠그는 사이 관리자가 を의 용법을 반려한다. 반려는 두 분석을 id
    # 순서로 잠그므로, 병합도 분석 행을 한 번에 id 순서로 잠가야 엇갈리지 않는다.
    base, variant, done, own = with_own_usage(fake_llm)
    wo = register(fake_llm, "本を読む", WO, "책을 읽는다")
    # 토큰: 0 本 / 1 を / 2 読ん / 3 で / 4 しまっ / 5 た
    fake_llm.response = {
        "translation_ko": "책을 읽어 버렸다",
        "spans": [span_answer(0, "usage", 1), span_answer(1, "usage", 2)],
    }
    analyze(client, "本を読んでしまった")
    # 토큰: 0 本 / 1 を / 2 見 / 3 ちゃっ / 4 た
    fake_llm.response = {
        "translation_ko": "책을 봐 버렸다",
        "spans": [span_answer(0, "usage", 1), span_answer(1, "usage", 2)],
    }
    analyze(client, "本を見ちゃった")
    result = {}
    make_stale = patterns.make_stale

    def reject():
        try:
            review.reject_usage(wo.usages.get())
            result["rejected"] = True
        finally:
            connection.close()

    def reject_meanwhile(*args, **kwargs):
        # 병합이 처음 분석 행을 잠근 직후 반려가 시작되게 한다.
        monkeypatch.setattr(patterns, "make_stale", make_stale)
        locked = make_stale(*args, **kwargs)
        thread = threading.Thread(target=reject)
        thread.start()
        wait_until_blocked()
        result["thread"] = thread
        return locked

    monkeypatch.setattr(patterns, "make_stale", reject_meanwhile)

    review.link_variant(variant, base, {own.pk: done.pk})
    result["thread"].join()

    assert result.get("rejected")
    assert fresh(variant).variant_of == base


def test_linking_without_own_usages_leaves_analyses_of_the_base_fresh(fake_llm):
    # 원형의 후보는 그대로라 원형 분석까지 다시 분석하지 않는다(#63과 같다).
    base, variant = base_and_variant(fake_llm)
    SentenceAnalysis.objects.update(is_stale=False)

    review.link_variant(variant, base)

    assert not SentenceAnalysis.objects.get(span_matches__pattern=base).is_stale


def test_usage_transition_on_a_usage_merged_away_meanwhile_is_refused(fake_llm):
    # admin이 용법 목록을 읽은 뒤 그 용법이 원형 용법으로 합쳐져 지워졌다.
    base, variant, done, own = with_own_usage(fake_llm)
    review.link_variant(variant, base, {own.pk: done.pk})

    with pytest.raises(review.Refused):
        review.approve_usage(own)


def test_usage_transition_on_a_usage_moved_meanwhile_is_refused(fake_llm):
    # admin이 회화체 소속으로 읽은 용법이 그사이 원형 아래로 옮겨졌다. 회화체 목록에서 고른
    # 상태 변경을 원형과 그 회화체들이 함께 쓰는 용법에 적용하지 않는다.
    base, variant, _, own = with_own_usage(fake_llm)
    review.link_variant(variant, base, {own.pk: None})

    with pytest.raises(review.Refused):
        review.approve_usage(own)

    assert GrammarUsage.objects.get(pk=own.pk).status == "pending"


def test_usage_transition_checks_the_pattern_a_usage_was_moved_to(fake_llm):
    # admin이 용법 목록을 읽은 뒤 그 용법이 원형 아래로 옮겨졌고, 원형은 반려됐다.
    base, variant, _, own = with_own_usage(fake_llm)
    review.link_variant(variant, base, {own.pk: None})
    review.reject_pattern(fresh(base))

    with pytest.raises(review.Refused):
        review.approve_usage(own)

    assert GrammarUsage.objects.get(pk=own.pk).status == "pending"


USAGES = "/admin/analysis/grammarusage/"


@pytest.mark.parametrize("moved", [False, True], ids=["합침", "옮김"])
def test_usage_form_opened_before_merging_is_not_saved(admin_client, fake_llm, monkeypatch, moved):
    # 회화체 용법의 변경 화면을 연 뒤 그 용법이 원형으로 합쳐지거나 옮겨졌다. 화면은 회화체
    # 조건으로 예문을 검사하므로, 저장하면 원형 소속 용법에 원형에 걸리지 않는 예문이 남는다.
    base, variant, done, own = with_own_usage(fake_llm)
    stale = GrammarUsage.objects.get(pk=own.pk)
    review.link_variant(variant, base, {own.pk: None if moved else done.pk})
    monkeypatch.setattr(GrammarUsageAdmin, "get_object", lambda *args: stale)

    response = admin_client.post(
        f"{USAGES}{own.pk}/change/",
        {"explanation_ko": "새 설명", "example_ja": "本を忘れちゃった"},
    )

    assert response.status_code == 200
    assert "옮겨졌습니다" in html.unescape(response.content.decode())
    if moved:
        assert GrammarUsage.objects.get(pk=own.pk).example_ja is None


@pytest.mark.parametrize("moved", [False, True], ids=["합침", "옮김"])
def test_inline_usage_opened_before_merging_is_not_saved(admin_client, fake_llm, moved):
    # 회화체 패턴 화면을 연 뒤 그 용법이 원형으로 합쳐지거나 옮겨졌다.
    base, variant, done, own = with_own_usage(fake_llm)
    form = pattern_form(
        variant, **{"usages-0-explanation_ko": "새 설명", "usages-0-example_ja": "本を忘れちゃった"}
    )
    review.link_variant(variant, base, {own.pk: None if moved else done.pk})

    response = admin_client.post(f"{PATTERNS}{variant.pk}/change/", form)

    assert response.status_code == 200
    assert "옮겨졌습니다" in html.unescape(response.content.decode())
    if moved:
        assert GrammarUsage.objects.get(pk=own.pk).explanation_ko != "새 설명"


def test_inline_rows_are_not_shown_against_the_wrong_usage_after_a_move(admin_client, fake_llm):
    # 회화체에 용법이 둘인데 화면을 연 뒤 앞 용법만 원형 아래로 옮겨졌다. admin은 보낸 행과
    # 지금 목록을 순서대로 짝지으므로, 옮겨진 용법의 행이 남은 용법의 행으로 보이면 안 된다.
    base, variant, _, own = with_own_usage(fake_llm)
    with transaction.atomic():
        other, _ = patterns.add_usage(variant, "유감", "아쉬운 마음을 담는다", None)
    form = pattern_form(variant, **{"usages-1-explanation_ko": "새 설명"})
    # 반려된 용법은 연결해도 회화체에 남는다.
    review.reject_usage(other)
    review.link_variant(variant, base, {own.pk: None})

    response = admin_client.post(f"{PATTERNS}{variant.pk}/change/", form)

    page = html.unescape(response.content.decode())
    assert response.status_code == 200
    assert "옮겨졌습니다" in page
    assert f"{USAGES}{other.pk}/change/" not in page
    assert GrammarUsage.objects.get(pk=other.pk).explanation_ko == "아쉬운 마음을 담는다"


@pytest.mark.parametrize("moved", [False, True], ids=["합침", "옮김"])
def test_staff_without_usage_permissions_cannot_merge_or_move(
    client, django_user_model, fake_llm, moved
):
    # 패턴 변경 권한만 있는 스태프는 용법을 옮기거나 지울 수 없다.
    base, variant, done, own = with_own_usage(fake_llm)
    staff = django_user_model.objects.create_user("staff", password="pw", is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(codename__in=["view_grammarpattern", "change_grammarpattern"])
    )
    client.force_login(staff)

    act(
        client,
        "link_variant",
        variant,
        base_pattern_id=str(base.pk),
        apply="1",
        **{f"usage_{own.pk}": "move" if moved else str(done.pk)},
    )

    assert fresh(variant).variant_of is None
    assert GrammarUsage.objects.get(pk=own.pk).pattern == variant
