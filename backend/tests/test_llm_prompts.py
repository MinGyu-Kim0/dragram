"""용도별 프롬프트·스키마 모듈. 용도마다 지켜야 할 조립 규칙을 보고, 공용 문단을 나눠 쓰는
첫 분석·판정 지시문만 최종 문자열을 고정한다.
"""

import hashlib

import pytest

from analysis.jmdict import SENSE_TAG_NAMES, WHOLE_WORD_TAGS
from analysis.llm_analyze import INSTRUCTIONS, NAME_TYPES, RESPONSE_SCHEMA, TOKEN_FIXES
from analysis.llm_fill import (
    CONNECTION_SCHEMA,
    FILL_INSTRUCTIONS,
    FILL_SCHEMA,
)
from analysis.llm_judge import JUDGE_INSTRUCTIONS, judge_schema
from analysis.llm_rewrite import REWRITE_SCHEMA
from analysis.llm_rules import (
    FUNCTION_TAGS_RULE,
    KOREAN_EQUIVALENT_RULE,
    NUMBER_RULES,
    SPAN_VERDICTS,
    span_answers_schema,
)
from analysis.llm_words import DEFINE_SCHEMA, GLOSS_SCHEMA


def objects(schema):
    """스키마 안의 모든 object 칸."""
    if isinstance(schema, dict):
        if "properties" in schema:
            yield schema
        for value in schema.values():
            yield from objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from objects(value)


@pytest.mark.parametrize(
    "schema",
    [
        RESPONSE_SCHEMA,
        judge_schema(True),
        judge_schema(False),
        REWRITE_SCHEMA,
        GLOSS_SCHEMA,
        DEFINE_SCHEMA,
        FILL_SCHEMA,
        CONNECTION_SCHEMA,
    ],
    ids=["analyze", "judge+translation", "judge", "rewrite", "gloss", "define", "fill", "conn"],
)
def test_every_object_requires_all_its_fields_and_forbids_others(schema):
    # OpenAI 구조화 출력의 strict 모드가 요구하는 모양이다.
    found = list(objects(schema))

    assert found
    for item in found:
        assert set(item["required"]) == set(item["properties"])
        assert item["additionalProperties"] is False


@pytest.mark.parametrize(
    "instructions",
    [INSTRUCTIONS, JUDGE_INSTRUCTIONS, FILL_INSTRUCTIONS],
    ids=["analyze", "judge", "fill"],
)
def test_prompts_that_write_usages_share_the_same_rules(instructions):
    assert KOREAN_EQUIVALENT_RULE in instructions
    assert FUNCTION_TAGS_RULE in instructions


@pytest.mark.parametrize(
    ("instructions", "digest"),
    [
        (
            INSTRUCTIONS + NUMBER_RULES,
            "0b304ea518e45e0285078e48a296052586cbec97d2e5f3a46aa92ace017dabf9",
        ),
        (
            JUDGE_INSTRUCTIONS + NUMBER_RULES,
            "8012576d0c6eeb4a33c9533cc6ffe287155b6f424c0c795db5350c87c5e7db46",
        ),
    ],
    ids=["analyze", "judge"],
)
def test_prompts_stay_the_same_letter_for_letter(instructions, digest):
    # 공용 문단을 옮기는 정리가 보내는 글을 바꾸지 않게 고정한다(#430). 문구를 일부러 바꿀 때만
    # 이 값을 함께 고친다.
    assert hashlib.sha256(instructions.encode()).hexdigest() == digest


def test_translation_is_asked_again_only_when_rechecking():
    assert list(judge_schema(True)["properties"]) == ["translation_ko", "spans"]
    assert list(judge_schema(False)["properties"]) == ["spans"]


def test_only_asking_again_receives_alternatives():
    with_alternatives = span_answers_schema(True)["items"]
    without = span_answers_schema(False)["items"]

    assert "alternatives" in with_alternatives["required"]
    assert "alternatives" not in without["properties"]


def test_each_call_gets_its_own_span_schema():
    # 대안 칸을 더해도 다음 호출의 스키마에 남지 않는다.
    span_answers_schema(True)

    assert "alternatives" not in span_answers_schema(False)["items"]["required"]


def test_first_analysis_offers_the_shared_verdicts():
    item = RESPONSE_SCHEMA["properties"]["spans"]["items"]

    assert item["properties"]["verdict"]["enum"] == list(SPAN_VERDICTS)


def test_first_analysis_closes_translation_and_verdicts_before_new_patterns():
    # 응답을 칸이 닫히는 대로 먼저 알리므로 이 순서가 먼저 알리기의 전제다(#204).
    order = list(RESPONSE_SCHEMA["properties"])

    assert order.index("translation_ko") < order.index("spans") < order.index("new_patterns")


def test_first_analysis_constrains_token_fixes_and_name_types():
    schema = str(RESPONSE_SCHEMA)

    assert all(fix in schema for fix in TOKEN_FIXES)
    assert all(name_type in schema for name_type in NAME_TYPES)


def test_new_words_can_only_use_known_dictionary_tags():
    schema = str(DEFINE_SCHEMA)

    assert all(tag in schema for tag in SENSE_TAG_NAMES)
    assert all(tag in schema for tag in WHOLE_WORD_TAGS)
