"""분석 API: 문법 패턴 등록과 매칭 재사용(#35)."""

import threading
from unittest.mock import ANY

import pytest
from django.db import connection

from analysis import morphology, patterns
from analysis import worker as patterns_views
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternMorpheme,
    PatternSetVersion,
    ReviewStatus,
    SpanMatch,
)
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import (
    analyze,
    connected_client,
    new_pattern,
    new_usage,
    saved_analyses,
    span_answer,
)

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
            "state": "decided",
            "connection": ANY,
            "pattern_name": "ている",
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "pos_tags": ["particle", "verb"],
            "function_tags": [],
            "function_tags_review_status": None,
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
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
            "state": "decided",
            "connection": ANY,
            "pattern_name": "ている",
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "pos_tags": ["particle", "verb"],
            "function_tags": [],
            "function_tags_review_status": None,
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
        }
    ]
    assert GrammarUsage.objects.count() == 1
    assert GrammarPattern.objects.count() == 1


@pytest.mark.parametrize(("verdict", "candidate_id"), [("not_applicable", None)])
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
    # 해당 없음은 새 문법을 만들지 않는다.
    assert (GrammarPattern.objects.count(), GrammarUsage.objects.count()) == (1, 1)


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
    assert saved_analyses().count() == 1
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
        # 칸 길이(255자)를 넘는 이름
        new_pattern((1, "lemma"), (2, "lemma"), pattern_name="て" * 256),
        new_pattern((1, "lemma"), (2, "lemma"), usage_name="진" * 256),
        # 문장 전체를 인용한 설명
        new_pattern((1, "lemma"), (2, "lemma"), explanation_ko="走っている에서 진행"),
        "not an object",
    ],
)
def test_invalid_new_grammar_fails_and_nothing_is_stored(client, fake_llm, proposal):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [proposal]}

    response = analyze(client, "走っている")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert saved_analyses().count() == 0
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
        # 고정 토큰에 조사·조동사가 없다(#133). 토큰: 0 目指す / 1 ソフトバンク
        ("目指すソフトバンク", new_pattern((0, "form"), (1, "lemma"))),
        # 조사는 아무거나로만 있다. 토큰: 0 本 / 1 を / 2 読む
        ("本を読む", new_pattern((0, "lemma"), (1, "any"), (2, "lemma"))),
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


def test_content_only_grammar_is_dropped_and_rest_of_answer_is_saved(client, fake_llm):
    # 토큰: 0 走っ / 1 て / 2 いる. 走る만 고정한 제안은 빼고 ている는 등록한다.
    content_only = new_pattern((0, "form"), pattern_name="動詞", usage_name="동작")
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [content_only, TEIRU]}

    response = analyze(client, "走っている")

    assert [g["name"] for g in response.json()["grammar"]] == ["진행"]
    assert list(GrammarPattern.objects.values_list("name", flat=True)) == ["ている"]
    assert list(GrammarUsage.objects.values_list("name", flat=True)) == ["진행"]
    assert PatternMorpheme.objects.count() == 2
    assert saved_analyses().get().translation_ko == "달리고 있다"
    assert len(fake_llm.requests) == 1
    assert fake_llm.rejudge_requests == []


def test_content_only_grammar_matching_existing_pattern_is_not_asked_again(client, fake_llm):
    # 규칙 전에 쌓인 내용어만의 패턴. 토큰: 0 目指す / 1 ソフトバンク
    morphs = morphology.morphemes("目指すソフトバンク")
    conditions = [patterns.condition(morphs[0], "form"), patterns.condition(morphs[1], "lemma")]
    patterns.register(conditions, "動詞+名詞", "수식", "꾸민다", "目指すソフトバンク", None)
    fake_llm.response = {
        "translation_ko": "목표로 하는 소프트뱅크",
        "new_patterns": [new_pattern((0, "form"), (1, "lemma"))],
    }

    response = analyze(client, "目指すソフトバンク")

    assert response.json()["grammar"] == []
    assert fake_llm.rejudge_requests == []
    assert GrammarPattern.objects.count() == 1


@pytest.mark.parametrize(
    ("sentence", "proposal"),
    [
        # 토큰: 0 泳ぐ / 1 こと / 2 が / 3 出来る
        ("泳ぐことができる", new_pattern((1, "lemma"), (2, "lemma"), (3, "lemma"))),
        # 토큰: 0 勝ち / 1 まし / 2 た
        ("勝ちました", new_pattern((1, "lemma"), (2, "lemma"))),
    ],
)
def test_grammar_fixing_a_function_word_is_registered(client, fake_llm, sentence, proposal):
    fake_llm.response = {"translation_ko": "번역", "new_patterns": [proposal]}

    analyze(client, sentence)

    assert GrammarPattern.objects.count() == 1


def propose_teiru_again(client, fake_llm, rejudge_answers):
    """예문이 없어 비활성이던 ている와 같은 조건을 다른 문장에서 다시 제안한다."""
    register_teiru(client, fake_llm, example_ja="走っている")
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과")],
    }
    fake_llm.rejudge_response = {"spans": rejudge_answers}
    return analyze(client, "彼が来ている")


def test_new_grammar_with_existing_pattern_is_asked_again_with_its_usages(client, fake_llm):
    response = propose_teiru_again(client, fake_llm, [span_answer(0, "usage", 1)])

    # 새 용법(결과)은 버리고, 기존 용법 목록으로 한 번 더 묻는다. 번역도 함께 준다.
    [rejudge] = fake_llm.rejudge_requests
    assert rejudge["sentence"] == "彼が来ている"
    assert rejudge["translation_ko"] == "그가 와 있다"
    assert rejudge["spans"] == [
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
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert GrammarPattern.objects.count() == 1
    assert GrammarUsage.objects.count() == 1


def test_asked_again_span_may_add_new_usage_to_existing_pattern(client, fake_llm):
    usage = new_usage(
        usage_name="결과 상태",
        explanation_ko="동작의 결과가 남아 있다",
        example_ja="窓が開いている",
    )

    response = propose_teiru_again(client, fake_llm, [span_answer(0, "unfound", new_usage=usage)])

    assert [item["name"] for item in response.json()["grammar"]] == ["결과 상태"]
    assert GrammarPattern.objects.count() == 1
    assert list(GrammarUsage.objects.order_by("id").values_list("name", flat=True)) == [
        "진행",
        "결과 상태",
    ]


@pytest.mark.parametrize(
    "answers",
    [[], [span_answer(0, "usage", 2)], [span_answer(0, "unfound")], "not a list"],
)
def test_invalid_answer_when_asked_again_fails_and_nothing_is_stored(client, fake_llm, answers):
    response = propose_teiru_again(client, fake_llm, answers)

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert saved_analyses().count() == 1


def test_sentence_without_existing_pattern_is_not_asked_again(client, fake_llm):
    register_teiru(client, fake_llm)

    assert fake_llm.rejudge_requests == []


def test_same_pattern_proposed_twice_in_one_sentence_is_registered_once_and_shown_twice(
    client, fake_llm
):
    # 토큰: 0 走っ / 1 て / 2 い / 3 て / 4 いる (lemma 고정이라 い와 いる는 같은 居る)
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [TEIRU, new_pattern((3, "lemma"), (4, "lemma"))],
    }

    response = analyze(client, "走っていている")

    assert GrammarPattern.objects.count() == 1
    assert GrammarUsage.objects.count() == 1
    assert fake_llm.rejudge_requests == []
    # 용법 이름이 같으므로 두 자리 모두 처음 등록한 용법으로 보인다.
    grammar = response.json()["grammar"]
    assert [(item["start"], item["end"], item["name"]) for item in grammar] == [
        (2, 4, "진행"),
        (4, 7, "진행"),
    ]


def test_same_pattern_with_different_usages_in_one_sentence_keeps_both_usages(client, fake_llm):
    # 토큰: 0 走っ / 1 て / 2 い / 3 て / 4 いる. 같은 조건이 다른 용법으로 두 번 나온다.
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [
            TEIRU,
            new_pattern(
                (3, "lemma"),
                (4, "lemma"),
                usage_name="결과 상태",
                explanation_ko="동작의 결과가 남아 있다",
                example_ja="窓が開いている",
            ),
        ],
    }

    response = analyze(client, "走っていている")

    assert GrammarPattern.objects.count() == 1
    assert [item["name"] for item in response.json()["grammar"]] == ["진행", "결과 상태"]
    assert GrammarUsage.objects.count() == 2


def test_same_new_grammar_proposed_twice_at_same_place_is_one_span(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU, TEIRU]}

    response = analyze(client, "走っている")

    assert len(response.json()["grammar"]) == 1
    assert SpanMatch.objects.count() == 1
    assert GrammarUsage.objects.count() == 1


def test_new_grammar_on_the_range_of_a_candidate_span_is_dropped(client, fake_llm):
    register_teiru(client, fake_llm)
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる. 활용형만 더 고정해 morpheme_key가 다르다(#233).
    narrower = new_pattern((3, "lemma"), (4, "form"), usage_name="결과 상태")
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "usage", 1)],
        "new_patterns": [narrower],
    }

    response = analyze(client, "彼が来ている")

    assert GrammarPattern.objects.count() == 1
    assert fake_llm.rejudge_requests == []
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]


def test_existing_grammar_proposed_twice_at_same_place_is_asked_once(client, fake_llm):
    register_teiru(client, fake_llm, example_ja="走っている")
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    teiru = new_pattern((3, "lemma"), (4, "lemma"))
    fake_llm.response = {"translation_ko": "그가 와 있다", "new_patterns": [teiru, teiru]}
    fake_llm.rejudge_response = {"spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, "彼が来ている")

    assert len(fake_llm.rejudge_requests[0]["spans"]) == 1
    assert len(response.json()["grammar"]) == 1


def test_pattern_is_activated_by_valid_example_of_later_same_proposal(client, fake_llm):
    # 토큰: 0 走っ / 1 て / 2 い / 3 て / 4 いる. 첫 제안의 예문은 원문을 베꼈고 뒤 제안은 통과한다.
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [
            new_pattern((1, "lemma"), (2, "lemma"), example_ja="走っていている"),
            new_pattern(
                (3, "lemma"),
                (4, "lemma"),
                usage_name="결과 상태",
                explanation_ko="동작의 결과가 남아 있다",
                example_ja="窓が開いている",
            ),
        ],
    }

    analyze(client, "走っていている")

    pattern = GrammarPattern.objects.get()
    assert pattern.is_active
    assert pattern.test_cases == [{"text": "窓が開いている", "should_match": True}]
    assert PatternSetVersion.objects.get().version == 1
    # 용법 예문은 그 용법이 쓴 예문만 쓴다.
    assert dict(GrammarUsage.objects.values_list("name", "example_ja")) == {
        "진행": None,
        "결과 상태": "窓が開いている",
    }


def test_usage_example_is_taken_from_later_same_usage_when_first_fails(client, fake_llm):
    # 새 패턴: 첫 제안의 예문은 원문을 베꼈고, 같은 용법 이름의 뒤 제안 예문은 통과한다.
    # 토큰: 0 走っ / 1 て / 2 い / 3 て / 4 いる
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [
            new_pattern((1, "lemma"), (2, "lemma"), example_ja="走っていている"),
            new_pattern((3, "lemma"), (4, "lemma"), example_ja="雨が降っている"),
        ],
    }

    analyze(client, "走っていている")

    assert GrammarUsage.objects.get().example_ja == "雨が降っている"


def test_new_usage_example_is_taken_from_later_same_usage_when_first_fails(client, fake_llm):
    register_nagara(client, fake_llm)
    # 기존 패턴(ながら)이 두 번 걸리고 두 구간 모두 같은 새 용법을 낸다. 첫 예문은 패턴에 안 걸린다.
    # 토큰: 0 知っ / 1 て / 2 い / 3 ながら / 4 、 / 5 狭い / 6 ながら
    fake_llm.response = {
        "translation_ko": "알면서도, 좁으면서도",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage(example_ja="狭い部屋だ")),
            span_answer(1, "unfound", new_usage=new_usage()),
        ],
    }

    analyze(client, "知っていながら、狭いながら")

    assert GrammarUsage.objects.get(name="역접").example_ja == "狭いながら快適だ"


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_pattern_created_concurrently_is_asked_again_with_its_usages(fake_llm, monkeypatch):
    # 같은 조건의 패턴이 없다고 확인한 뒤, 등록하기 직전에 다른 요청이 먼저 등록하고 커밋한다.
    register = patterns.register

    def other_request_registers_first(*args, **kwargs):
        monkeypatch.setattr(patterns, "register", register)
        saved_response = fake_llm.response

        def other_request():
            try:
                register_teiru(connected_client(), fake_llm)
            finally:
                connection.close()

        thread = threading.Thread(target=other_request)
        thread.start()
        thread.join()
        fake_llm.response = saved_response
        return register(*args, **kwargs)

    monkeypatch.setattr(patterns, "register", other_request_registers_first)
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과")],
    }
    fake_llm.rejudge_response = {"spans": [span_answer(0, "usage", 1)]}

    response = analyze(connected_client(), "彼が来ている")

    assert len(fake_llm.rejudge_requests) == 1
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert GrammarPattern.objects.count() == 1
    assert GrammarUsage.objects.count() == 1


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


@pytest.mark.parametrize("example_ja", ["です", "です。", "「です」"])
def test_example_same_as_sentence_of_single_token_is_rejected(client, fake_llm, example_ja):
    # 형태소가 하나여도 원문 그대로인 예문은 새로 쓴 문장이 아니다. 토큰: 0 です
    fake_llm.response = {
        "translation_ko": "입니다",
        "new_patterns": [new_pattern((0, "lemma"), pattern_name="です", example_ja=example_ja)],
    }

    analyze(client, "です")

    assert not GrammarPattern.objects.get().is_active
    assert GrammarUsage.objects.get().example_ja is None


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


@pytest.mark.parametrize(
    ("sentence", "matches"),
    [
        # 1그룹 동사 음편형(撥音便·イ音便) 뒤의 で는 て로 본다.
        ("本を読んでしまう", True),
        ("泳いでしまう", True),
        ("食べてしまう", True),
        # ない 뒤의 で는 그대로 で라 별개다.
        ("遊ばないでしまう", False),
    ],
)
def test_voiced_function_word_after_sound_change_matches_unvoiced_pattern(
    client, fake_llm, sentence, matches
):
    # 토큰: 0 書い / 1 て / 2 しまう
    fake_llm.response = {
        "translation_ko": "써 버린다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                (2, "lemma"),
                pattern_name="てしまう",
                usage_name="완료",
                example_ja="全部食べてしまう",
            )
        ],
    }
    analyze(client, "書いてしまう")

    analyze(client, sentence)

    assert len(fake_llm.requests[1]["spans"]) == (1 if matches else 0)


@pytest.mark.parametrize(
    ("sentence", "registered_from", "proposal"),
    [
        # だ·だら → た(가정형). 토큰: 0 読ん / 1 だら
        (
            "読んだら",
            "食べたら",
            new_pattern((1, "form"), pattern_name="たら", example_ja="雨が降ったら"),
        ),
        # でる → てる, じゃう → ちゃう. 토큰: 0 食べ / 1 てる
        (
            "読んでる",
            "食べてる",
            new_pattern((1, "lemma"), pattern_name="てる", example_ja="本を見てる"),
        ),
        (
            "読んじゃう",
            "食べちゃう",
            new_pattern((1, "lemma"), pattern_name="ちゃう", example_ja="全部見ちゃう"),
        ),
        # どく → とく, じまう → ちまう, でく → てく, じゃ(接続助詞) → ちゃ(#63)
        (
            "飲んどく",
            "言っとく",
            new_pattern((1, "lemma"), pattern_name="とく", example_ja="手紙を書いとく"),
        ),
        (
            "飲んじまった",
            "食べちまった",
            new_pattern((1, "lemma"), pattern_name="ちまう", example_ja="全部見ちまった"),
        ),
        (
            "読んでく",
            "食べてく",
            new_pattern((1, "lemma"), pattern_name="てく", example_ja="パンを買ってく"),
        ),
        (
            "読んじゃいけない",
            "食べちゃいけない",
            new_pattern((1, "lemma"), pattern_name="ちゃ", example_ja="ここで見ちゃ駄目"),
        ),
    ],
)
def test_other_voiced_auxiliaries_after_sound_change_match_unvoiced_patterns(
    client, fake_llm, sentence, registered_from, proposal
):
    fake_llm.response = {"translation_ko": "번역", "new_patterns": [proposal]}
    analyze(client, registered_from)

    analyze(client, sentence)

    assert len(fake_llm.requests[1]["spans"]) == 1


def asked_usages(fake_llm):
    return [[c["name"] for c in span["candidates"]] for span in fake_llm.requests[-1]["spans"]]


def test_naide_is_not_read_as_te(client, fake_llm):
    # 토큰: 0 食べ / 1 ない / 2 で
    fake_llm.response = {
        "translation_ko": "먹지 말고",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                (2, "lemma"),
                pattern_name="ないで",
                usage_name="부정 지시",
                example_ja="泣かないでほしい",
            )
        ],
    }
    analyze(client, "食べないで")
    # 토큰: 0 見 / 1 て / 2 ください
    fake_llm.response = {
        "translation_ko": "봐 주세요",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                (2, "lemma"),
                pattern_name="てください",
                usage_name="요청",
                example_ja="早く来てください",
            )
        ],
    }
    analyze(client, "見てください")
    fake_llm.response = {"translation_ko": "가지 말아 주세요"}

    analyze(client, "行かないでください")

    assert asked_usages(fake_llm) == [["부정 지시"]]


def test_chaikenai_and_teikenai_are_different_patterns(client, fake_llm):
    # 토큰: 0 食べ / 1 ちゃ / 2 いけ / 3 ない
    fake_llm.response = {
        "translation_ko": "먹으면 안 된다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                (2, "lemma"),
                (3, "lemma"),
                pattern_name="ちゃいけない",
                usage_name="금지",
                example_ja="ここで寝ちゃいけない",
            )
        ],
    }
    analyze(client, "食べちゃいけない")
    # 토큰: 0 生き / 1 て / 2 いけ / 3 ない
    fake_llm.response = {
        "translation_ko": "살아갈 수 없다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                (2, "lemma"),
                (3, "lemma"),
                pattern_name="ていけない",
                usage_name="지속 불가",
                example_ja="一人で暮らしていけない",
            )
        ],
    }
    analyze(client, "生きていけない")
    fake_llm.response = {"translation_ko": "번역"}

    analyze(client, "これを食べちゃいけない")
    assert asked_usages(fake_llm) == [["금지"]]

    analyze(client, "その給料じゃ食べていけない")
    assert asked_usages(fake_llm) == [["지속 불가"]]


def register_nagara(client, fake_llm):
    # 토큰: 0 歩き / 1 ながら
    fake_llm.response = {
        "translation_ko": "걸으면서",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                pattern_name="ながら",
                usage_name="동시 동작",
                explanation_ko="두 동작을 함께 한다",
                example_ja="音楽を聞きながら歩く",
            )
        ],
    }
    analyze(client, "歩きながら")


def test_unfound_span_adds_new_usage_under_the_same_pattern(client, fake_llm):
    register_nagara(client, fake_llm)
    # 토큰: 0 知っ / 1 て / 2 い / 3 ながら. 동시 동작으로는 설명되지 않는 역접
    fake_llm.response = {
        "translation_ko": "알면서도",
        "spans": [span_answer(0, "unfound", new_usage=new_usage())],
    }

    response = analyze(client, "知っていながら")

    assert response.json()["grammar"] == [
        {
            "start": 4,
            "end": 7,
            "state": "decided",
            "connection": ANY,
            "pattern_name": "ながら",
            "name": "역접",
            "explanation_ko": "앞 내용과 반대되는 뒤 내용을 잇는다",
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "pos_tags": ["particle"],
            "function_tags": [],
            "function_tags_review_status": None,
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
        }
    ]
    assert GrammarPattern.objects.count() == 1
    usage = GrammarUsage.objects.get(name="역접")
    assert (usage.status, usage.origin, usage.example_ja) == ("pending", "llm", "狭いながら快適だ")
    assert usage.pattern == GrammarPattern.objects.get()

    # 다음 문장에는 두 용법이 모두 후보로 간다.
    analyze(client, "食べながら")
    candidates = fake_llm.requests[-1]["spans"][0]["candidates"]
    assert [c["name"] for c in candidates] == ["동시 동작", "역접"]


@pytest.mark.parametrize(
    "usage",
    [
        None,
        "not an object",
        new_usage(usage_name=""),
        new_usage(explanation_ko=" "),
        new_usage(example_ja=None),
        new_usage(usage_name="⟨N1⟩"),
        new_usage(explanation_ko="⟨N1⟩번"),
        new_usage(usage_name="역" * 256),
        # 문장 전체를 인용한 설명
        new_usage(explanation_ko="知っていながら에서 역접"),
    ],
)
def test_invalid_new_usage_fails_and_nothing_is_stored(client, fake_llm, usage):
    register_nagara(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "알면서도",
        "spans": [span_answer(0, "unfound", new_usage=usage)],
    }

    response = analyze(client, "知っていながら")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert GrammarUsage.objects.count() == 1
    assert saved_analyses().count() == 1


def test_new_usage_with_existing_name_is_not_added(client, fake_llm):
    register_nagara(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "알면서도",
        "spans": [span_answer(0, "unfound", new_usage=new_usage(usage_name="동시 동작"))],
    }

    response = analyze(client, "知っていながら")

    assert response.json()["grammar"] == []
    assert GrammarUsage.objects.count() == 1
    assert SpanMatch.objects.filter(state="unfound").count() == 1


@pytest.mark.parametrize("example_ja", ["知っていながら", "彼は知っていながら黙った", "狭い部屋だ"])
def test_new_usage_with_rejected_example_is_added_without_example(client, fake_llm, example_ja):
    register_nagara(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "알면서도",
        "spans": [span_answer(0, "unfound", new_usage=new_usage(example_ja=example_ja))],
    }

    analyze(client, "知っていながら")

    assert GrammarUsage.objects.get(name="역접").example_ja is None


def test_new_grammar_same_as_judged_span_is_not_asked_again(client, fake_llm):
    register_teiru(client, fake_llm)
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    # 이미 후보 구간으로 판정한 ている를 새 구문으로도 낸다.
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "usage", 1)],
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과")],
    }

    response = analyze(client, "彼が来ている")

    assert fake_llm.rejudge_requests == []
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]


def test_response_quoting_the_sentence_fails_before_asking_again(client, fake_llm):
    register_teiru(client, fake_llm, example_ja="走っている")
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [
            new_pattern((3, "lemma"), (4, "lemma"), explanation_ko="彼が来ている에서 진행")
        ],
    }

    response = analyze(client, "彼が来ている")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert fake_llm.rejudge_requests == []


# 토큰: 0 昨日 / 1 図書館 / 2 で / 3 本 / 4 を / 5 読ん / 6 で / 7 いる
LIBRARY = "昨日図書館で本を読んでいる"


@pytest.mark.parametrize(
    ("example_ja", "copied"),
    [
        # 문법 구간 밖의 원문을 8자(昨日図書館で本を) 그대로 썼다.
        ("昨日図書館で本を見ている", True),
        # 7자(図書館で本を読ん의 일부)까지는 베낀 것으로 보지 않는다.
        ("図書館で本を見ている", False),
        ("雨が降っている", False),
    ],
)
def test_example_copying_part_of_sentence_is_rejected(client, fake_llm, example_ja, copied):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [new_pattern((6, "lemma"), (7, "lemma"), example_ja=example_ja)],
    }

    analyze(client, LIBRARY)

    assert GrammarPattern.objects.get().is_active is not copied


def test_grammar_span_itself_does_not_count_as_copying(client, fake_llm, settings):
    settings.EXAMPLE_COPY_LENGTH = 3
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる. 예문의 ている(3자)는 문법 구간이라 세지 않는다.
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), example_ja="雨が降っている")],
    }

    analyze(client, "彼が来ている")

    assert GrammarPattern.objects.get().is_active


def test_copy_length_comes_from_settings(client, fake_llm, settings):
    settings.EXAMPLE_COPY_LENGTH = 4
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="図書館で雑誌を見ている")
        ],
    }

    analyze(client, LIBRARY)

    assert not GrammarPattern.objects.get().is_active


def test_new_usage_example_copying_part_of_sentence_is_not_stored(client, fake_llm):
    register_nagara(client, fake_llm)
    # 토큰: 0 昨日 / 1 図書館 / 2 で / 3 本 / 4 を / 5 読み / 6 ながら
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽으면서",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage(example_ja="昨日図書館で本を見ながら"))
        ],
    }

    analyze(client, "昨日図書館で本を読みながら")

    assert GrammarUsage.objects.get(name="역접").example_ja is None


def rewritten(*texts):
    return {"examples": [{"example_id": i, "example_ja": t} for i, t in enumerate(texts)]}


def test_copied_examples_are_rewritten_once_together(client, fake_llm):
    # 토큰: 0 走っ / 1 て / 2 い / 3 て / 4 いる. 두 용법의 예문이 모두 원문을 베꼈다.
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [
            new_pattern((1, "lemma"), (2, "lemma"), example_ja="走っていている"),
            new_pattern(
                (3, "lemma"),
                (4, "lemma"),
                usage_name="결과 상태",
                explanation_ko="동작의 결과가 남아 있다",
                example_ja="彼は走っていている",
            ),
        ],
    }
    fake_llm.rewrite_response = rewritten("雨が降っている", "窓が開いている")

    analyze(client, "走っていている")

    [request] = fake_llm.rewrite_requests
    assert request["sentence"] == "走っていている"
    assert request["examples"] == [
        {
            "example_id": 0,
            "pattern_name": "ている",
            "usage_name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "rejected_example": "走っていている",
        },
        {
            "example_id": 1,
            "pattern_name": "ている",
            "usage_name": "결과 상태",
            "explanation_ko": "동작의 결과가 남아 있다",
            "rejected_example": "彼は走っていている",
        },
    ]
    pattern = GrammarPattern.objects.get()
    assert pattern.is_active
    assert pattern.test_cases == [{"text": "雨が降っている", "should_match": True}]
    assert dict(GrammarUsage.objects.values_list("name", "example_ja")) == {
        "진행": "雨が降っている",
        "결과 상태": "窓が開いている",
    }


def test_example_copied_again_after_rewrite_is_registered_inactive(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }
    fake_llm.rewrite_response = rewritten("昨日図書館で本を探している")

    analyze(client, LIBRARY)

    assert len(fake_llm.rewrite_requests) == 1
    pattern = GrammarPattern.objects.get()
    assert not pattern.is_active
    assert pattern.test_cases == []
    assert GrammarUsage.objects.get().example_ja is None


def test_rewritten_example_must_still_match_the_pattern(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }
    fake_llm.rewrite_response = rewritten("雨が降る")

    analyze(client, LIBRARY)

    assert not GrammarPattern.objects.get().is_active


def test_copied_new_usage_example_is_rewritten(client, fake_llm):
    register_nagara(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽으면서",
        "spans": [
            span_answer(0, "unfound", new_usage=new_usage(example_ja="昨日図書館で本を見ながら"))
        ],
    }
    fake_llm.rewrite_response = rewritten("狭いながら快適だ")

    analyze(client, "昨日図書館で本を読みながら")

    assert fake_llm.rewrite_requests[0]["examples"][0]["pattern_name"] == "ながら"
    assert GrammarUsage.objects.get(name="역접").example_ja == "狭いながら快適だ"


def test_example_rejected_for_other_reasons_is_not_rewritten(client, fake_llm):
    # 패턴에 걸리지 않는 예문은 베낀 것이 아니라 다시 쓰게 하지 않는다.
    register_teiru(client, fake_llm, example_ja="雨が降る")

    assert fake_llm.rewrite_requests == []
    assert not GrammarPattern.objects.get().is_active


@pytest.mark.parametrize(
    "answer",
    [
        {"examples": []},
        {"examples": [{"example_id": 1, "example_ja": "雨が降っている"}]},
        {"examples": [{"example_id": 0, "example_ja": ""}]},
        {
            "examples": [
                {"example_id": 0, "example_ja": "雨が降っている"},
                {"example_id": 0, "example_ja": "窓が開いている"},
            ]
        },
        {"examples": "not a list"},
        "not an object",
    ],
)
def test_invalid_rewrite_answer_keeps_the_analysis_without_example(client, fake_llm, answer):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }
    fake_llm.rewrite_response = answer

    response = analyze(client, LIBRARY)

    # 보조 호출 하나 때문에 번역·문법을 버리지 않고, 예문 없이 등록한다.
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert saved_analyses().count() == 1
    assert not GrammarPattern.objects.get().is_active
    assert GrammarUsage.objects.get().example_ja is None


def test_failed_rewrite_call_keeps_the_analysis_without_example(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }
    fake_llm.rewrite_error = BusinessError(AnalysisError.FAILED, "LLM 예문 다시 쓰기 호출 실패")

    response = analyze(client, LIBRARY)

    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert not GrammarPattern.objects.get().is_active


def test_copied_example_is_not_rewritten_when_same_usage_has_a_valid_one(client, fake_llm):
    # 토큰: 0 走っ / 1 て / 2 い / 3 て / 4 いる
    # 같은 조건·같은 용법 이름의 뒤 제안 예문이 통과한다.
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [
            new_pattern((1, "lemma"), (2, "lemma"), example_ja="走っていている"),
            new_pattern((3, "lemma"), (4, "lemma"), example_ja="雨が降っている"),
        ],
    }

    analyze(client, "走っていている")

    assert fake_llm.rewrite_requests == []
    assert GrammarUsage.objects.get().example_ja == "雨が降っている"


@pytest.mark.parametrize(("example_ja", "copied"), [("雪が降った", True), ("彼が来た", False)])
def test_any_token_inside_grammar_span_counts_as_copying(
    client, fake_llm, settings, example_ja, copied
):
    settings.EXAMPLE_COPY_LENGTH = 2
    # 토큰: 0 雨 / 1 が / 2 降っ / 3 た. 고정한 が·た는 세지 않지만 아무거나인 降っ는 원문 글자다.
    fake_llm.response = {
        "translation_ko": "비가 왔다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"), (2, "any"), (3, "lemma"), pattern_name="が〜た", example_ja=example_ja
            )
        ],
    }

    analyze(client, "雨が降った")

    assert GrammarPattern.objects.get().is_active is not copied


def test_calls_of_one_request_share_one_client(client, fake_llm, monkeypatch):
    # 요청 전체 마감 시각을 클라이언트가 지니므로 분석·다시 쓰기가 한 클라이언트를 쓴다.
    created = []
    monkeypatch.setattr(
        patterns_views.llm,
        "get_client",
        lambda record: created.append(1) or fake_llm.connect(record),
    )
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }

    analyze(client, LIBRARY)

    assert len(fake_llm.rewrite_requests) == 1
    assert len(created) == 1


def test_copied_example_that_does_not_match_the_pattern_is_not_rewritten(client, fake_llm):
    # 원문 8자를 베꼈지만 ている도 없어 어차피 쓸 수 없는 예문이다.
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を読む")
        ],
    }

    analyze(client, LIBRARY)

    assert fake_llm.rewrite_requests == []
    assert not GrammarPattern.objects.get().is_active


def test_rewritten_example_too_long_to_analyze_keeps_the_analysis(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }
    # SudachiPy 입력 한도(49,149바이트)를 넘는 예문
    fake_llm.rewrite_response = rewritten("雨が降っている" + "あ" * 17000)

    response = analyze(client, LIBRARY)

    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert not GrammarPattern.objects.get().is_active


def test_copying_across_a_fixed_token_counts_as_one_copy(client, fake_llm):
    # 토큰: 0 私 / 1 は / 2 昨日 / 3 雨 / 4 が / 5 降っ / 6 て / 7 も / 8 学校 / 9 に / 10 行く
    # ても 앞뒤의 원문(は昨日雨が降っ + 学校)을 이어서 9자 베꼈다. 고정한 ても는 세지 않는다.
    fake_llm.response = {
        "translation_ko": "나는 어제 비가 와도 학교에 간다",
        "new_patterns": [
            new_pattern(
                (6, "lemma"),
                (7, "lemma"),
                pattern_name="ても",
                usage_name="양보",
                explanation_ko="앞 내용과 상관없이 뒤 내용이 성립한다",
                example_ja="兄は昨日雨が降っても学校へ行く",
            )
        ],
    }

    analyze(client, "私は昨日雨が降っても学校に行く")

    assert not GrammarPattern.objects.get().is_active


def test_copying_across_a_fixed_token_written_differently_counts_as_one_copy(client, fake_llm):
    # 토큰: 0 冬 / 1 に / 2 雨 / 3 が / 4 降っ / 5 て / 6 くる / 7 と / 8 寒い
    # 고정한 くる를 같은 lemma의 来る로 바꿔 써도 앞뒤의 원문(冬に雨が降っ + と寒い) 9자를 이어서
    # 베낀 것이다.
    fake_llm.response = {
        "translation_ko": "겨울에 비가 내리기 시작하면 춥다",
        "new_patterns": [
            new_pattern(
                (5, "lemma"),
                (6, "lemma"),
                pattern_name="てくる",
                usage_name="변화의 시작",
                explanation_ko="어떤 상태로 바뀌기 시작한다",
                example_ja="冬に雨が降って来ると寒い",
            )
        ],
    }

    analyze(client, "冬に雨が降ってくると寒い")

    assert not GrammarPattern.objects.get().is_active


def test_copying_a_fixed_token_outside_the_example_match_counts_as_one_copy(
    client, fake_llm, settings
):
    settings.EXAMPLE_COPY_LENGTH = 4
    # 토큰: 0 雨 / 1 が / 2 降っ / 3 た / 4 学校. 예문의 패턴 매치는 雪が来た이고, 그 밖에서
    # 원문의 降っ + た + 学校를 이어 베꼈다. 매치 밖의 た도 원문 고정 토큰과 같은 글자로 잇는다.
    fake_llm.response = {
        "translation_ko": "비가 내린 학교",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                (2, "any"),
                (3, "lemma"),
                pattern_name="が〜た",
                example_ja="雪が来た、降った学校へ行く",
            )
        ],
    }

    analyze(client, "雨が降った学校")

    assert not GrammarPattern.objects.get().is_active


def test_copied_example_of_new_usage_with_existing_name_is_not_rewritten(client, fake_llm):
    register_nagara(client, fake_llm)
    # 같은 이름의 용법이 이미 있어 어차피 더하지 않는다.
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽으면서",
        "spans": [
            span_answer(
                0,
                "unfound",
                new_usage=new_usage(usage_name="동시 동작", example_ja="昨日図書館で本を見ながら"),
            )
        ],
    }

    analyze(client, "昨日図書館で本を読みながら")

    assert fake_llm.rewrite_requests == []


@pytest.mark.parametrize(
    "example_ja",
    [
        # 짧은 예문으로 받으므로 길이 상한(200자)을 넘으면 쓰지 않는다.
        "あ" * 200 + "雨が降っている",
        # 형태소 분석 한도(49,149바이트)를 넘는 예문도 분석을 실패시키지 않는다.
        "あ" * 17000 + "雨が降っている",
    ],
)
def test_too_long_example_is_not_used_and_keeps_the_analysis(client, fake_llm, example_ja):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [new_pattern((6, "lemma"), (7, "lemma"), example_ja=example_ja)],
    }

    response = analyze(client, LIBRARY)

    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert not GrammarPattern.objects.get().is_active
    assert fake_llm.rewrite_requests == []
