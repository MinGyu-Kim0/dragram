"""분석 API: 문법 패턴 등록과 매칭 재사용(#35)."""

import pytest

from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternMorpheme,
    PatternSetVersion,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
)
from tests.analysis.helpers import analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))


def test_new_grammar_is_registered_as_unreviewed_and_shown(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}

    response = analyze(client, "走っている")

    assert response.json()["grammar"] == [
        {
            "start": 2,
            "end": 5,
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "review_status": "pending",
        }
    ]


def register_teiru(client, fake_llm, **overrides):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [{**TEIRU, **overrides}],
    }
    analyze(client, "走っている")


def test_same_grammar_in_another_sentence_is_offered_as_candidate_and_reused(client, fake_llm):
    register_teiru(client, fake_llm)
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, "彼が来ている")

    assert fake_llm.requests[1]["spans"] == [
        {
            "span_id": 0,
            "start_token_id": 3,
            "end_token_id": 4,
            "candidates": [
                {
                    "candidate_id": 1,
                    "name": "진행",
                    "explanation_ko": "동작이 이어지고 있음을 나타낸다",
                }
            ],
        }
    ]
    # LLM은 설명을 쓰지 않고 ID만 골랐다. 첫 문장의 용법 설명이 그대로 보인다.
    assert response.json()["grammar"] == [
        {
            "start": 3,
            "end": 6,
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "review_status": "pending",
        }
    ]
    assert GrammarUsage.objects.count() == 1
    assert GrammarPattern.objects.count() == 1


@pytest.mark.parametrize(("verdict", "candidate_id"), [("not_applicable", None), ("unfound", None)])
def test_span_without_chosen_usage_is_not_shown(client, fake_llm, verdict, candidate_id):
    register_teiru(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, verdict, candidate_id)],
    }

    response = analyze(client, "彼が来ている")

    assert response.status_code == 200
    assert response.json()["grammar"] == []
    assert SpanMatch.objects.filter(state=verdict).count() == 1


def test_cached_sentence_reads_grammar_from_span_matches(client, fake_llm):
    register_teiru(client, fake_llm)
    first = analyze(client, "走っている")

    second = analyze(client, " 走っている。")

    assert len(fake_llm.requests) == 1
    assert [(g["start"], g["end"]) for g in second.json()["grammar"]] == [(3, 6)]
    assert second.json()["grammar"][0]["name"] == first.json()["grammar"][0]["name"]


def test_grammar_whose_usage_or_pattern_is_rejected_is_not_shown(client, fake_llm):
    register_teiru(client, fake_llm)
    GrammarUsage.objects.update(status=ReviewStatus.REJECTED)

    response = analyze(client, "走っている")

    assert response.json()["grammar"] == []


def test_grammar_shows_approved_only_when_usage_and_patterns_are_approved(client, fake_llm):
    register_teiru(client, fake_llm)
    GrammarUsage.objects.update(status=ReviewStatus.APPROVED)
    assert analyze(client, "走っている").json()["grammar"][0]["review_status"] == "pending"

    GrammarPattern.objects.update(status=ReviewStatus.APPROVED)

    assert analyze(client, "走っている").json()["grammar"][0]["review_status"] == "approved"


def test_activating_new_pattern_raises_pattern_set_version(client, fake_llm):
    register_teiru(client, fake_llm)

    assert GrammarPattern.objects.get().is_active
    assert PatternSetVersion.objects.get().version == 1


@pytest.mark.parametrize(
    "answers",
    [
        # 그 구간에 주지 않은 후보 ID
        [span_answer(0, "usage", 2)],
        [span_answer(0, "usage", None)],
        [span_answer(0, "usage", True)],
        # 없는 구간, 같은 구간을 두 번, 빠진 구간
        [span_answer(1, "usage", 1)],
        [span_answer(0, "usage", 1), span_answer(0, "not_applicable")],
        [],
        [span_answer(0, "maybe")],
        "not a list",
    ],
)
def test_invalid_span_answer_fails_and_nothing_is_stored(client, fake_llm, answers):
    register_teiru(client, fake_llm)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": answers}

    response = analyze(client, "彼が来ている")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 1
    assert SpanMatch.objects.count() == 1


@pytest.mark.parametrize(
    "proposal",
    [
        # 범위 밖·잘못된 토큰 ID, 없는 표시, 빈 토큰
        new_pattern((1, "lemma"), (3, "lemma")),
        new_pattern((-1, "lemma"), (0, "lemma")),
        new_pattern((True, "lemma"), (2, "lemma")),
        new_pattern((1, "lemma"), (2, "fixed")),
        new_pattern(),
        # 공용 용법은 모든 문장이 함께 쓰므로 숫자 자리표시자를 받지 않는다.
        new_pattern((1, "lemma"), (2, "lemma"), usage_name="⟨N1⟩"),
        new_pattern((1, "lemma"), (2, "lemma"), explanation_ko="⟨N1⟩개"),
        new_pattern((1, "lemma"), (2, "lemma"), pattern_name="⟨N1⟩"),
        new_pattern((1, "lemma"), (2, "lemma"), example_ja=""),
        # 문장 전체를 인용한 설명
        new_pattern((1, "lemma"), (2, "lemma"), explanation_ko="走っている에서 진행"),
        "not an object",
    ],
)
def test_invalid_new_grammar_fails_and_nothing_is_stored(client, fake_llm, proposal):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [proposal]}

    response = analyze(client, "走っている")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0
    assert GrammarPattern.objects.count() == 0


@pytest.mark.parametrize(
    ("sentence", "proposal"),
    [
        # 처음·끝 토큰이 아무거나. 토큰: 0 走っ / 1 て / 2 いる
        ("走っている", new_pattern((0, "any"), (1, "lemma"), (2, "lemma"))),
        ("走っている", new_pattern((1, "lemma"), (2, "any"))),
        # 사이가 빈 토큰과 거꾸로 된 순서
        ("走っている", new_pattern((0, "lemma"), (2, "lemma"))),
        ("走っている", new_pattern((2, "lemma"), (1, "lemma"))),
        # 숫자 토큰을 고정하면 공용 패턴에 원문 숫자가 들어간다. 토큰: 0 3 / 1 人 / 2 で
        ("3人で", new_pattern((0, "lemma"), (1, "lemma"), (2, "lemma"), example_ja="5人で")),
    ],
)
def test_new_grammar_breaking_pattern_rules_is_not_registered(client, fake_llm, sentence, proposal):
    fake_llm.response = {"translation_ko": "번역 ⟨N1⟩", "new_patterns": [proposal]}
    if not any(ch.isdigit() for ch in sentence):
        fake_llm.response["translation_ko"] = "번역"

    response = analyze(client, sentence)

    assert response.status_code == 200
    assert response.json()["grammar"] == []
    assert GrammarPattern.objects.count() == 0
    assert SpanMatch.objects.get().state == "unfound"


def test_new_grammar_with_existing_pattern_is_not_registered_again(client, fake_llm):
    # 예문이 없어 비활성이라 매칭에 쓰이지 않던 패턴과 같은 조건을 다시 제안한다.
    register_teiru(client, fake_llm, example_ja="走っている")
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과")],
    }

    response = analyze(client, "彼が来ている")

    assert response.json()["grammar"] == []
    assert GrammarUsage.objects.count() == 1
    assert SpanMatch.objects.filter(state="unfound").get().pattern == GrammarPattern.objects.get()


@pytest.mark.parametrize(
    "example_ja",
    [
        # 원문 키 텍스트 전체를 포함한다(사이에 기호를 끼워도).
        "走っている",
        "彼は走っている。",
        "彼は走っ・ている",
        # 패턴에 걸리지 않는다.
        "雨が降る",
        # 자리표시자를 쓴 예문
        "⟨N1⟩人が来ている",
    ],
)
def test_new_grammar_with_rejected_example_is_registered_inactive(client, fake_llm, example_ja):
    register_teiru(client, fake_llm, example_ja=example_ja)

    pattern = GrammarPattern.objects.get()
    assert not pattern.is_active
    assert pattern.test_cases == []
    assert GrammarUsage.objects.get().example_ja is None
    assert PatternSetVersion.objects.get().version == 0

    # 이 문장에는 보이지만 다음 문장의 매칭에는 쓰이지 않는다.
    assert len(analyze(client, "走っている").json()["grammar"]) == 1
    analyze(client, "彼が来ている")
    assert fake_llm.requests[-1]["spans"] == []


def test_new_example_is_stored_as_usage_example_and_first_test_case(client, fake_llm):
    register_teiru(client, fake_llm)

    pattern = GrammarPattern.objects.get()
    assert pattern.test_cases == [{"text": "雨が降っている", "should_match": True}]
    assert pattern.status == "pending"
    usage = GrammarUsage.objects.get()
    assert (usage.example_ja, usage.status, usage.origin) == ("雨が降っている", "pending", "llm")


def test_example_may_contain_sentence_of_single_token(client, fake_llm):
    # 형태소 하나로 된 문장은 그 토큰을 쓰는 것이 원문을 베끼는 것이 아니다. 토큰: 0 です
    fake_llm.response = {
        "translation_ko": "입니다",
        "new_patterns": [new_pattern((0, "lemma"), pattern_name="です", example_ja="学生です")],
    }

    analyze(client, "です")

    assert GrammarPattern.objects.get().is_active


def test_pattern_conditions_follow_lemma_rules(client, fake_llm):
    # 토큰: 0 食べ / 1 たら. 조동사는 원형(た), 내용어는 정규형, 활용형은 form일 때만 둔다.
    fake_llm.response = {
        "translation_ko": "먹으면",
        "new_patterns": [
            new_pattern((0, "lemma"), (1, "form"), pattern_name="たら", example_ja="雨が降ったら")
        ],
    }
    analyze(client, "食べたら")

    assert list(
        PatternMorpheme.objects.order_by("seq").values_list(
            "lemma", "pos1", "pos2", "conjugation_form"
        )
    ) == [("食べる", "動詞", "一般", None), ("た", "助動詞", None, "仮定形-一般")]


def test_conjugation_condition_separates_conditional_from_past(client, fake_llm):
    # 토큰: 0 食べ / 1 たら. 가정형 た만 고정한 한 토큰 패턴
    fake_llm.response = {
        "translation_ko": "먹으면",
        "new_patterns": [new_pattern((1, "form"), pattern_name="たら", example_ja="雨が降ったら")],
    }
    analyze(client, "食べたら")

    analyze(client, "食べた")  # 終止形 た
    analyze(client, "行ったら")

    assert fake_llm.requests[1]["spans"] == []
    assert len(fake_llm.requests[2]["spans"]) == 1


def test_any_token_matches_exactly_one_token(client, fake_llm):
    # 토큰: 0 雨 / 1 が / 2 降っ / 3 た
    fake_llm.response = {
        "translation_ko": "비가 왔다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"), (2, "any"), (3, "lemma"), pattern_name="が〜た", example_ja="彼が来た"
            )
        ],
    }
    analyze(client, "雨が降った")

    analyze(client, "雪が降った")
    analyze(client, "雨がよく降った")  # が와 た 사이에 두 토큰

    assert len(fake_llm.requests[1]["spans"]) == 1
    assert fake_llm.requests[2]["spans"] == []
