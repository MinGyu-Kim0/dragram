"""후보가 하나인 판별 대상 구간은 그 용법 내용을 확인 중 항목에 함께 싣는다(#203)."""

import pytest

from analysis.models import GrammarPattern, GrammarUsage, ReviewStatus
from tests.analysis.helpers import analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))
# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"


def register_teiru(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}
    analyze(client, "走っている")
    return GrammarPattern.objects.get()


def test_checking_span_with_one_candidate_carries_its_usage(client, fake_llm):
    pattern = register_teiru(client, fake_llm)
    pattern.usages.update(korean_equivalent="~고 있다", korean_equivalent_status="pending")
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, KITEIRU)

    [item] = response.events[0]["checking"]
    assert item["usage"] == {
        "name": "진행",
        "explanation_ko": "동작이 이어지고 있음을 나타낸다",
        "korean_equivalent": "~고 있다",
        "korean_equivalent_review_status": "pending",
        "pos_tags": ["particle", "verb"],
        "function_tags": [],
        "function_tags_review_status": None,
        "review_status": "pending",
        "register": "standard",
        "variant_of": None,
    }


def test_checking_span_with_several_candidates_carries_no_usage(client, fake_llm):
    pattern = register_teiru(client, fake_llm)
    GrammarUsage.objects.create(
        pattern=pattern,
        name="결과 상태",
        explanation_ko="동작의 결과가 남아 있음을 나타낸다",
        status=ReviewStatus.PENDING,
        origin=GrammarUsage.Origin.LLM,
    )
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, KITEIRU)

    [item] = response.events[0]["checking"]
    assert [c["name"] for c in item["candidates"]] == ["진행", "결과 상태"]
    assert item["usage"] is None
