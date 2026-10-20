"""분석 API: 문법 패턴 등록과 매칭 재사용(#35)."""

import threading

import pytest
from django.db import connection
from django.test import Client

from analysis import patterns
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternMorpheme,
    PatternSetVersion,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
)
from tests.analysis.helpers import analyze, new_pattern, new_usage, span_answer

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
    assert SentenceAnalysis.objects.count() == 1


def test_sentence_without_existing_pattern_is_not_asked_again(client, fake_llm):
    register_teiru(client, fake_llm)

    assert fake_llm.rejudge_requests == []


def test_same_pattern_proposed_twice_in_one_sentence_is_registered_once(client, fake_llm):
    # 토큰: 0 走っ / 1 て / 2 いる / 3 て / 4 いる (같은 조건이 두 번)
    fake_llm.response = {
        "translation_ko": "번역",
        "new_patterns": [TEIRU, new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과")],
    }

    analyze(client, "走っていている")

    assert GrammarPattern.objects.count() == 1
    assert GrammarUsage.objects.count() == 1
    assert fake_llm.rejudge_requests == []


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_pattern_created_concurrently_is_asked_again_with_its_usages(fake_llm, monkeypatch):
    # 같은 조건의 패턴이 없다고 확인한 뒤, 등록하기 직전에 다른 요청이 먼저 등록하고 커밋한다.
    register = patterns.register

    def other_request_registers_first(*args):
        monkeypatch.setattr(patterns, "register", register)
        saved_response = fake_llm.response

        def other_request():
            try:
                register_teiru(Client(), fake_llm)
            finally:
                connection.close()

        thread = threading.Thread(target=other_request)
        thread.start()
        thread.join()
        fake_llm.response = saved_response
        return register(*args)

    monkeypatch.setattr(patterns, "register", other_request_registers_first)
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과")],
    }
    fake_llm.rejudge_response = {"spans": [span_answer(0, "usage", 1)]}

    response = analyze(Client(), "彼が来ている")

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
    ],
)
def test_other_voiced_auxiliaries_after_sound_change_match_unvoiced_patterns(
    client, fake_llm, sentence, registered_from, proposal
):
    fake_llm.response = {"translation_ko": "번역", "new_patterns": [proposal]}
    analyze(client, registered_from)

    analyze(client, sentence)

    assert len(fake_llm.requests[1]["spans"]) == 1


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
            "name": "역접",
            "explanation_ko": "앞 내용과 반대되는 뒤 내용을 잇는다",
            "review_status": "pending",
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
    assert SentenceAnalysis.objects.count() == 1


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
