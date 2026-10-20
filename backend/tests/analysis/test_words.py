"""분석 API: 단어 구간·검증·걸러 내기·재사용."""

import pytest

from analysis.models import SentenceAnalysis
from tests.analysis.helpers import analyze, word_item

pytestmark = pytest.mark.django_db


def test_new_sentence_returns_words_at_original_positions(client, fake_llm):
    # 토큰: 0 私 / 1 は / 2 学生 / 3 です
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "words": [
            {"token_id": 0, "lemma": "私", "reading": "わたし", "meaning_ko": "나"},
            {"token_id": 2, "lemma": "学生", "reading": "がくせい", "meaning_ko": "학생"},
        ],
    }

    response = analyze(client, "私は学生です。")

    assert response.json()["words"] == [
        {
            "start": 0,
            "end": 1,
            "lemma": "私",
            "reading": "わたし",
            "meaning_ko": "나",
            "review_status": "pending",
        },
        {
            "start": 2,
            "end": 4,
            "lemma": "学生",
            "reading": "がくせい",
            "meaning_ko": "학생",
            "review_status": "pending",
        },
    ]


def test_llm_response_without_words_fails(client, fake_llm):
    fake_llm.fill_defaults = False
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "grammar": []}

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


@pytest.mark.parametrize(
    "words",
    [
        [word_item(token_id=4)],  # 범위 밖
        [word_item(token_id=-1)],
        [word_item(token_id="2")],
        [word_item(token_id=True)],
        [word_item(lemma="")],
        [word_item(reading=" ")],
        [word_item(meaning_ko="")],
        # 읽기는 가나(와 장음)로만 쓴다.
        [word_item(reading="gakusei")],
        [word_item(reading="学生")],
        [word_item(reading="がく生")],
        [word_item(reading="학생")],
        [word_item(reading="・")],  # 가타카나 블록의 문장부호는 가나가 아니다
        [word_item(reading="゠")],
        [word_item(reading="ー")],  # 가나 없이 장음만
        [word_item(meaning_ko="⟨N1⟩명")],  # 숫자가 없는 문장의 자리표시자
        [{"token_id": 2, "lemma": "学生", "reading": "がくせい"}],  # 뜻 없음
        ["not an object"],
        "not a list",
        None,
    ],
)
def test_invalid_words_fail_the_sentence_and_are_not_stored(client, fake_llm, words):
    # 토큰은 0~3 네 개다.
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "words": words}

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


def test_word_meaning_quoting_whole_sentence_fails_and_is_not_stored(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "words": [word_item(meaning_ko="私は学生です에서 학생")],
    }

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


@pytest.mark.parametrize(
    ("sentence", "translation", "dropped", "kept"),
    [
        # 숫자만 있는 토큰. 토큰: 0 3 / 1 人 / 2 で / 3 行く
        (
            "3人で行く",
            "⟨N1⟩명이서 간다",
            word_item(0, "⟨N1⟩", "⟨N1⟩", "⟨N1⟩"),
            word_item(3, "行く", "いく", "가다"),
        ),
        # 숫자가 섞인 토큰. LLM이 사전형에 숫자를 지어내면 다른 숫자 문장에 잘못 재사용된다.
        # 토큰: 0 X1 / 1 2 / 2 を / 3 買う
        (
            "X12を買う",
            "X⟨N1⟩를 산다",
            word_item(0, "X1", "えっくすいち", "X1"),
            word_item(3, "買う", "かう", "사다"),
        ),
        # 기호 토큰. 토큰: 0 行く / 1 ！
        (
            "行く！",
            "간다!",
            word_item(1, "！", "！", "느낌표"),
            word_item(0, "行く", "いく", "가다"),
        ),
        # 숫자열 뒤쪽 토큰(키 텍스트에서 빈 조각). 토큰: 0 X1 / 1 2 / 2 を / 3 買う
        (
            "X12を買う",
            "X⟨N1⟩를 산다",
            word_item(1, "2", "に", "2"),
            word_item(3, "買う", "かう", "사다"),
        ),
        # 조사·조동사는 단어가 아니라 문법이다. 토큰: 0 私 / 1 は / 2 学生 / 3 です
        ("私は学生です。", "나는 학생입니다.", word_item(1, "は", "は", "주제"), word_item(2)),
        ("私は学生です。", "나는 학생입니다.", word_item(3, "です", "です", "이다"), word_item(2)),
    ],
)
def test_words_on_number_or_symbol_tokens_are_dropped_and_the_rest_is_kept(
    client, fake_llm, sentence, translation, dropped, kept
):
    # 지침을 어긴 단어 하나 때문에 번역·문법까지 버리면 LLM을 다시 불러야 하므로 그 단어만 뺀다.
    fake_llm.response = {"translation_ko": translation, "words": [dropped, kept]}

    response = analyze(client, sentence)

    assert response.status_code == 200
    assert [word["lemma"] for word in response.json()["words"]] == [kept["lemma"]]
    [row] = SentenceAnalysis.objects.values("draft_analysis")
    assert [word["lemma"] for word in row["draft_analysis"]["words"]] == [kept["lemma"]]


def test_duplicate_word_for_same_token_keeps_only_the_first(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "words": [word_item(2, meaning_ko="학생"), word_item(2, meaning_ko="생도")],
    }

    response = analyze(client, "私は学生です。")

    assert [word["meaning_ko"] for word in response.json()["words"]] == ["학생"]


@pytest.mark.parametrize(
    "meaning",
    [
        "私 は 学生 です에서 학생",
        "私・は・学生・です에서 학생",
        "私\u200bは学生です에서 학생",
    ],
)
def test_word_meaning_quoting_whole_sentence_with_separators_fails(client, fake_llm, meaning):
    # 형태소 사이에 공백·가운데점·보이지 않는 문자를 넣어 인용해도 원문을 옮긴 것이다.
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "words": [word_item(meaning_ko=meaning)],
    }

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


def test_katakana_reading_of_loanword_is_kept_as_is(client, fake_llm):
    # 외래어(사전에 없는 새 말 포함)의 가타카나 읽기는 히라가나로 바꾸지 않는다.
    # 토큰: 0 コーヒー / 1 を / 2 飲む
    fake_llm.response = {
        "translation_ko": "커피를 마신다",
        "words": [
            word_item(0, "コーヒー", "コーヒー", "커피"),
            word_item(2, "飲む", "のむ", "마시다"),
        ],
    }

    response = analyze(client, "コーヒーを飲む")

    assert [word["reading"] for word in response.json()["words"]] == ["コーヒー", "のむ"]


def test_cached_sentence_returns_same_words(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "words": [word_item()]}
    first = analyze(client, "私は学生です。")

    second = analyze(client, "私は学生です。")

    assert second.json()["words"] == first.json()["words"]
    assert len(second.json()["words"]) == 1
    assert len(fake_llm.requests) == 1


def test_reused_words_point_at_same_characters_and_restore_numbers(client, fake_llm):
    # 토큰: 0 3 / 1 人 / 2 で / 3 行く
    fake_llm.response = {
        "translation_ko": "⟨N1⟩명이서 간다",
        "words": [word_item(token_id=3, lemma="行く", reading="いく", meaning_ko="가다")]
        + [word_item(token_id=1, lemma="人", reading="にん", meaning_ko="⟨N1⟩명의 명")],
    }
    analyze(client, "3人で行く")

    response = analyze(client, "  「12人で行く。」")

    words = response.json()["words"]
    assert [(word["start"], word["end"]) for word in words] == [(7, 9), (5, 6)]
    assert words[1]["meaning_ko"] == "12명의 명"
    assert len(fake_llm.requests) == 1


def test_reading_with_number_placeholder_fails(client, fake_llm):
    # 숫자와 겹치는 토큰은 단어에서 빠지므로, 다른 단어의 읽기에 자리표시자가 들어갈 일은 없다.
    # 토큰: 0 3 / 1 人 / 2 で / 3 行く
    fake_llm.response = {
        "translation_ko": "⟨N1⟩명이서 간다",
        "words": [word_item(3, "行く", "い⟨N1⟩く", "가다")],
    }

    response = analyze(client, "3人で行く")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0
