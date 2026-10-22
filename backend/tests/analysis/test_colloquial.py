"""회화체 패턴을 원형에 연결하기(#63)."""

import html

import pytest
from django.db import IntegrityError, transaction
from django.db.models import F
from django.test import Client

from analysis import review
from analysis.models import GrammarPattern, PatternSetVersion, SentenceAnalysis
from tests.analysis.helpers import analyze, new_pattern

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
