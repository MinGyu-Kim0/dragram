"""분석 API: 문법 구간·원문 위치·원문 인용 차단."""

import pytest

from analysis.models import SentenceAnalysis
from tests.analysis.helpers import analyze, new_pattern

pytestmark = pytest.mark.django_db


def proposal(first, last, example_ja, **texts):
    """first~last 토큰을 모두 lemma 고정으로 표시한 새 구문 제안."""
    tokens = [(token, "lemma") for token in range(first, last + 1)]
    return new_pattern(*tokens, example_ja=example_ja, **texts)


def test_new_sentence_returns_grammar_at_original_positions(client, fake_llm):
    # 토큰: 0 私 / 1 は / 2 学生 / 3 です
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "new_patterns": [
            proposal(3, 3, "猫です", usage_name="정중 です", explanation_ko="정중"),
            proposal(1, 1, "猫は好きだ", usage_name="주제 は", explanation_ko="주제"),
        ],
    }

    response = analyze(client, "私は学生です。")

    # 원문 순서로 보인다.
    assert response.json()["grammar"] == [
        {
            "start": 1,
            "end": 2,
            "name": "주제 は",
            "explanation_ko": "주제",
            "review_status": "pending",
        },
        {
            "start": 4,
            "end": 6,
            "name": "정중 です",
            "explanation_ko": "정중",
            "review_status": "pending",
        },
    ]


def test_grammar_spanning_tokens_covers_them_all(client, fake_llm):
    # 토큰: 0 食べ / 1 て / 2 いる
    fake_llm.response = {
        "translation_ko": "먹고 있다",
        "new_patterns": [proposal(1, 2, "見ている")],
    }

    response = analyze(client, "食べている")

    [item] = response.json()["grammar"]
    assert (item["start"], item["end"]) == (2, 5)


@pytest.mark.parametrize(
    ("first", "token_ranges", "examples", "second", "expected"),
    [
        # 앞 공백·감싼 괄호와 숫자 자릿수가 다르다. 토큰: 0 3 / 1 人 / 2 で / 3 行く
        (
            "3人で行く",
            [(2, 2), (1, 2)],
            ["車で行く", "5人で来た"],
            "  「12人で行く。」",
            [(5, 7), (6, 7)],
        ),
        # 지워지는 이모지는 UTF-16으로 두 칸이다. 토큰: 0 私 / 1 は / 2 学生 / 3 です
        ("私は学生です", [(1, 1)], ["猫は好きだ"], "😀私は学生です", [(3, 4)]),
        # 반각 가나는 탁점이 따로 한 글자다. 토큰: 0 ガクセイ / 1 です
        (
            "ガクセイです",
            [(0, 0), (1, 1)],
            ["ガクセイが来た", "猫です"],
            "ｶﾞｸｾｲです",
            [(0, 5), (5, 7)],
        ),
        # 결합 문자로 쓴 탁점. 토큰: 0 が / 1 好き
        ("が好き", [(0, 0)], ["雨が降る"], "が好き", [(0, 2)]),
        # 일본어 사이 공백과 전각 숫자. 토큰: 0 3 / 1 人 / 2 で / 3 行く
        ("3人で行く", [(2, 2)], ["車で行く"], "３人 で行く", [(3, 4)]),
        # 두 자리 이상 숫자 바로 뒤에서 시작하는 구간. 토큰: 0 3 / 1 で / 2 割る
        ("3で割る", [(1, 1), (1, 2)], ["車で行く", "水で割る"], "12で割る", [(2, 3), (2, 5)]),
        # 형태소가 숫자열 가운데에서 나뉘어도 뒤 구간은 숫자열 뒤에서 시작한다.
        # 토큰: 0 X1 / 1 2 / 2 で
        ("X12で", [(2, 2)], ["車で"], "X345で", [(4, 5)]),
        # 분해형 한글은 원문 세 글자가 한 글자가 된다. 토큰: 0 한 / 1 は
        ("한は", [(1, 1)], ["猫は"], "\u1112\u1161\u11abは", [(3, 4)]),
    ],
)
def test_reused_grammar_points_at_same_characters_in_each_original(
    client, fake_llm, first, token_ranges, examples, second, expected
):
    has_number = any(ch.isdigit() for ch in first)
    fake_llm.response = {
        "translation_ko": "번역 ⟨N1⟩" if has_number else "번역",
        "new_patterns": [
            proposal(start, end, example, usage_name=f"용법 {i}")
            for i, ((start, end), example) in enumerate(zip(token_ranges, examples, strict=True))
        ],
    }
    analyze(client, first)

    response = analyze(client, second)

    assert len(fake_llm.requests) == 1
    grammar = response.json()["grammar"]
    assert [(item["start"], item["end"]) for item in grammar] == expected


def test_sentence_without_grammar_returns_empty_grammar(client, fake_llm):
    fake_llm.response = {"translation_ko": "도쿄"}

    response = analyze(client, "東京")

    assert response.json()["grammar"] == []


def test_cached_sentence_returns_same_grammar(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "new_patterns": [proposal(1, 1, "猫は好きだ", usage_name="주제 は")],
    }
    first = analyze(client, "私は学生です。")

    second = analyze(client, "私は学生です。")

    assert second.json() == first.json()
    assert len(fake_llm.requests) == 1


@pytest.mark.parametrize(
    ("usage_name", "explanation"),
    [
        ("주제 は", "私は学生です에서 は는 주제"),
        ("私は学生です의 は", "주제"),
    ],
)
def test_grammar_text_quoting_whole_sentence_fails_and_is_not_stored(
    client, fake_llm, usage_name, explanation
):
    # 공용 테이블에 원문이 들어가지 않게, 문장 전체를 인용한 이름·설명은 받지 않는다.
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [
            proposal(1, 1, "猫は好きだ", usage_name=usage_name, explanation_ko=explanation)
        ],
    }

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


def test_grammar_spanning_whole_sentence_may_not_quote_it(client, fake_llm):
    # 구간이 문장 전체여도 여러 토큰이면 원문을 옮긴 것이다. 토큰: 0 私 / 1 は / 2 学生 / 3 です
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "new_patterns": [
            proposal(0, 3, "私は先生です", explanation_ko="私は学生です에서 は는 주제")
        ],
    }

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


def test_grammar_text_may_quote_sentence_that_is_the_grammar_span_itself(client, fake_llm):
    # 문법 구간이 곧 문장 전체면 그 구간 글자를 인용할 수밖에 없다. 토큰: 0 です
    fake_llm.response = {
        "translation_ko": "입니다",
        "new_patterns": [proposal(0, 0, "学生です", explanation_ko="です는 정중")],
    }

    response = analyze(client, "です")

    assert response.status_code == 200
    assert response.json()["grammar"][0]["explanation_ko"] == "です는 정중"


@pytest.mark.parametrize("missing", ["spans", "new_patterns"])
def test_llm_response_without_grammar_fails(client, fake_llm, missing):
    fake_llm.fill_defaults = False
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "spans": [], "new_patterns": []}
    fake_llm.response["words"] = []
    del fake_llm.response[missing]

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}


def test_sentence_of_only_symbols_is_not_treated_as_quoted(client, fake_llm):
    # 기호를 지우면 빈 문장이 되어도, 모든 글이 그 문장을 인용한 것으로 보지 않는다.
    # 토큰: 0 ！ / 1 ？
    fake_llm.response = {"translation_ko": "!?", "new_patterns": [proposal(0, 1, "えっ！？")]}

    response = analyze(client, "！？")

    assert response.status_code == 200


@pytest.mark.parametrize("sentence", ["えっ…", "そう‥"])
def test_symbols_split_into_empty_tokens_are_not_offered_as_tokens(client, fake_llm, sentence):
    # Sudachi는 …를 ...로 바꿔 길이 0인 토큰을 덧붙인다. 그런 토큰을 고르면 구간이 비어
    # 원문 위치로 바꾸지 못하고, 저장된 결과 때문에 같은 문장이 계속 실패했다.
    fake_llm.response = {"translation_ko": "어…"}
    analyze(client, sentence)

    assert all(token["surface"] for token in fake_llm.requests[0]["tokens"])
