"""긴 패턴 안의 구성 문법 표시(#65)."""

import pytest

from tests.analysis.helpers import analyze, new_pattern

pytestmark = pytest.mark.django_db

# 토큰: 0 食べ / 1 て / 2 しまっ / 3 た
TABETESHIMATTA = "食べてしまった"
TE = new_pattern(
    (1, "lemma"),
    pattern_name="て",
    usage_name="연결",
    explanation_ko="앞뒤 동작을 잇는다",
    example_ja="見て笑う",
)
TESHIMAU = new_pattern(
    (1, "lemma"),
    (2, "lemma"),
    pattern_name="てしまう",
    usage_name="완료",
    explanation_ko="동작을 끝까지 해 버린다",
    example_ja="見てしまう",
)


def analyze_with(client, fake_llm, *proposals, sentence=TABETESHIMATTA):
    fake_llm.response = {"translation_ko": "먹어 버렸다", "new_patterns": list(proposals)}
    return analyze(client, sentence)


def test_grammar_inside_a_longer_grammar_is_shown_in_its_parts(client, fake_llm):
    response = analyze_with(client, fake_llm, TESHIMAU, TE)

    assert response.json()["grammar"] == [
        {
            "start": 2,
            "end": 6,
            "state": "decided",
            "name": "완료",
            "explanation_ko": "동작을 끝까지 해 버린다",
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
            "parts": [
                {
                    "start": 2,
                    "end": 3,
                    "state": "decided",
                    "name": "연결",
                    "explanation_ko": "앞뒤 동작을 잇는다",
                    "review_status": "pending",
                    "register": "standard",
                    "variant_of": None,
                }
            ],
        }
    ]
