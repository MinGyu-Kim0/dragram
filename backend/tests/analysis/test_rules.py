"""판별 규칙(usage_rule)의 조건 형식과 판정(#55)."""

import pytest

from analysis.morphology import morphemes
from analysis.rules import condition_matches, condition_problem

# 토큰: 0 東京 / 1 で / 2 会う
TOKYO_DE = morphemes("東京で会う")


def test_morphemes_keep_the_pos_subcategory():
    tokyo, de, _ = TOKYO_DE
    assert (tokyo.pos, tokyo.pos2, tokyo.pos3) == ("名詞", "固有名詞", "地名")
    assert de.pos3 is None


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ([{"position": -1, "pos3": "地名"}], True),
        ([{"position": -1, "pos3": "人名"}], False),
        ([{"position": -1, "pos1": "名詞", "pos2": "固有名詞"}], True),
        ([{"position": 1, "lemma": "会う"}], True),
        ([{"position": 1, "lemma": "行く"}], False),
        ([{"position": 1, "pos1": "動詞", "conjugation_form": "終止形-一般"}], True),
        # 조건끼리는 모두 맞아야 한다.
        ([{"position": -1, "pos3": "地名"}, {"position": 1, "lemma": "行く"}], False),
        # 비운 칸은 아무거나다. 그 자리에 토큰만 있으면 맞는다.
        ([{"position": -1, "lemma": ""}], True),
        # 문장 처음·끝이라 그 자리에 토큰이 없으면 맞지 않는다.
        ([{"position": -2, "pos1": "名詞"}], False),
        ([{"position": 2}], False),
    ],
)
def test_condition_is_checked_on_tokens_around_the_span(condition, expected):
    assert condition_matches(condition, TOKYO_DE, 1, 1) is expected


def test_positions_count_from_the_span_edges():
    # 구간이 東京で(0~1)이면 +1은 会う다.
    assert condition_matches([{"position": 1, "lemma": "会う"}], TOKYO_DE, 0, 1)
    assert not condition_matches([{"position": -1}], TOKYO_DE, 0, 1)


@pytest.mark.parametrize(
    "condition",
    [
        [],
        {"position": -1},
        ["-1"],
        [{"lemma": "東京"}],
        [{"position": 0}],
        [{"position": 3}],
        [{"position": "1"}],
        [{"position": True}],
        [{"position": -1, "pos4": "x"}],
        [{"position": -1, "lemma": 1}],
    ],
)
def test_malformed_conditions_are_refused(condition):
    assert condition_problem(condition) is not None


def test_well_formed_condition_has_no_problem():
    assert condition_problem([{"position": -2, "pos1": "名詞"}, {"position": 2}]) is None
