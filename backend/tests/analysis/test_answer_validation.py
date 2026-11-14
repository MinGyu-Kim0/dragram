"""LLM 응답 검증이 OpenAI의 strict 스키마에 기대지 않고 서버에서 막는다(#415)."""

import pytest

from analysis.models import GrammarUsage
from tests.analysis.helpers import (
    analyze,
    new_pattern,
    new_usage,
    register,
    saved_analyses,
    span_answer,
)

pytestmark = pytest.mark.django_db

# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"


@pytest.fixture
def teiru(fake_llm):
    return register(fake_llm, "走っている", new_pattern((1, "lemma"), (2, "lemma")))


def test_new_usage_cannot_mark_its_own_example_as_checked(client, fake_llm, teiru):
    # 원문을 그대로 베낀 예문에 "이미 검사함" 칸을 붙여 보낸다.
    usage = new_usage("결과 상태", "동작의 결과가 남아 있다", KITEIRU) | {
        "checked_example": "検査していない例文だ"
    }
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "unfound", new_usage=usage)],
    }

    analyze(client, KITEIRU)

    # 예문 검사가 돌아 베낀 예문을 다시 쓰게 했고, 보낸 칸의 값은 저장되지 않는다.
    assert len(fake_llm.rewrite_requests) == 1
    assert GrammarUsage.objects.get(name="결과 상태").example_ja is None


def test_translation_with_nul_is_rejected(client, fake_llm):
    fake_llm.response = {"translation_ko": "그가\x00 와 있다"}

    response = analyze(client, KITEIRU)

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not saved_analyses().exists()


@pytest.mark.parametrize("field", ["usage_name", "explanation_ko", "example_ja"])
def test_new_usage_with_nul_is_rejected(client, fake_llm, teiru, field):
    usage = new_usage("결과 상태", "동작의 결과가 남아 있다", "窓が開いている")
    usage[field] = usage[field][:1] + "\x00" + usage[field][1:]
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "unfound", new_usage=usage)],
    }

    response = analyze(client, KITEIRU)

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not GrammarUsage.objects.filter(name__startswith="결").exists()
