"""회화체 패턴을 원형에 연결하기(#63)."""

import html
import threading

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.test import Client

from analysis import patterns, review
from analysis.models import GrammarPattern, GrammarUsage, PatternSetVersion, SentenceAnalysis
from tests.analysis.helpers import (
    analyze,
    new_pattern,
    new_usage,
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
    analyze(Client(), sentence)
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
    "name": "완료",
    "explanation_ko": "동작이 끝나 버렸음을 나타낸다",
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

    response = analyze(Client(), "全部食べてしまった")
    result["thread"].join()

    assert "error" not in response.json()
    assert result.get("unlinked")
    assert fresh(variant).variant_of is None
