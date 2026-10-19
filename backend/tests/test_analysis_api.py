import threading

import pytest
from django.db import connection
from django.test import Client

from analysis.models import SentenceAnalysis
from errors import AnalysisError, BusinessError

pytestmark = pytest.mark.django_db


def analyze(client, text):
    return client.post("/api/analyses/", {"text": text}, content_type="application/json")


def test_new_sentence_returns_translation(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json()["translation_ko"] == "나는 학생입니다."


def test_new_sentence_returns_grammar_at_original_positions(client, fake_llm):
    # 토큰: 0 私 / 1 は / 2 学生 / 3 です
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "grammar": [
            {"start_token_id": 1, "end_token_id": 1, "name": "주제 は", "explanation_ko": "주제"},
            {"start_token_id": 3, "end_token_id": 3, "name": "정중 です", "explanation_ko": "정중"},
        ],
    }

    response = analyze(client, "私は学生です。")

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
        "grammar": [
            {
                "start_token_id": 1,
                "end_token_id": 2,
                "name": "진행 ている",
                "explanation_ko": "진행",
            }
        ],
    }

    response = analyze(client, "食べている")

    [item] = response.json()["grammar"]
    assert (item["start"], item["end"]) == (2, 5)


def _grammar(*token_ranges):
    return [
        {"start_token_id": start, "end_token_id": end, "name": "문법", "explanation_ko": "설명"}
        for start, end in token_ranges
    ]


@pytest.mark.parametrize(
    ("first", "token_ranges", "second", "expected"),
    [
        # 앞 공백·감싼 괄호와 숫자 자릿수가 다르다. 토큰: 0 3 / 1 人 / 2 で / 3 行く
        ("3人で行く", [(2, 2), (0, 1)], "  「12人で行く。」", [(6, 7), (3, 6)]),
        # 지워지는 이모지는 UTF-16으로 두 칸이다. 토큰: 0 私 / 1 は / 2 学生 / 3 です
        ("私は学生です", [(1, 1)], "😀私は学生です", [(3, 4)]),
        # 반각 가나는 탁점이 따로 한 글자다. 토큰: 0 ガクセイ / 1 です
        ("ガクセイです", [(0, 0), (1, 1)], "ｶﾞｸｾｲです", [(0, 5), (5, 7)]),
        # 결합 문자로 쓴 탁점. 토큰: 0 が / 1 好き
        ("が好き", [(0, 0)], "か\u3099好き", [(0, 2)]),
        # 일본어 사이 공백과 전각 숫자. 토큰: 0 3 / 1 人 / 2 で / 3 行く
        ("3人で行く", [(2, 2)], "３人 で行く", [(3, 4)]),
        # 두 자리 이상 숫자 바로 뒤에서 시작하는 구간. 토큰: 0 3 / 1 で / 2 割る
        ("3で割る", [(1, 1), (0, 1)], "12で割る", [(2, 3), (0, 3)]),
        # 형태소가 숫자열 가운데에서 나뉘면 뒤 토큰도 숫자열 전체를 덮는다. 토큰: 0 X1 / 1 2 / 2 で
        ("X12で", [(1, 1), (2, 2)], "X345で", [(1, 4), (4, 5)]),
        # 분해형 한글은 원문 세 글자가 한 글자가 된다. 토큰: 0 한 / 1 は
        ("한は", [(1, 1)], "한は", [(3, 4)]),
    ],
)
def test_reused_grammar_points_at_same_characters_in_each_original(
    client, fake_llm, first, token_ranges, second, expected
):
    has_number = any(ch.isdigit() for ch in first)
    fake_llm.response = {"translation_ko": "번역 ⟨N1⟩" if has_number else "번역"}
    fake_llm.response["grammar"] = _grammar(*token_ranges)
    analyze(client, first)

    response = analyze(client, second)

    assert len(fake_llm.requests) == 1
    grammar = response.json()["grammar"]
    assert [(item["start"], item["end"]) for item in grammar] == expected


def test_placeholders_in_grammar_text_are_restored_for_each_original(client, fake_llm):
    # 토큰: 0 3 / 1 で / 2 割る. LLM은 숫자 대신 자리표시자를 본다.
    fake_llm.response = {
        "translation_ko": "⟨N1⟩으로 나눈다",
        "grammar": [
            {
                "start_token_id": 1,
                "end_token_id": 1,
                "name": "⟨N1⟩で의 で",
                "explanation_ko": "⟨N1⟩으로 나눈다는 뜻",
            }
        ],
    }
    analyze(client, "3で割る")

    response = analyze(client, "1で割る")

    [item] = response.json()["grammar"]
    # 번역과 같은 규칙으로 숫자를 되돌리고 뒤따르는 조사를 고친다(일 → 로).
    assert item["name"] == "1で의 で"
    assert item["explanation_ko"] == "1로 나눈다는 뜻"
    assert len(fake_llm.requests) == 1


def test_token_inside_number_at_sentence_end_covers_whole_number(client, fake_llm):
    # Sudachi는 X12를 X1 / 2로 나눈다. 뒤 토큰은 키 텍스트에서 빈 조각이다.
    fake_llm.response = {"translation_ko": "X⟨N1⟩", "grammar": _grammar((1, 1))}

    first = analyze(client, "X12")
    second = analyze(client, "X12")

    assert first.status_code == second.status_code == 200
    [item] = second.json()["grammar"]
    assert (item["start"], item["end"]) == (1, 3)


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


def test_sentence_without_grammar_returns_empty_grammar(client, fake_llm):
    fake_llm.response = {"translation_ko": "도쿄", "grammar": []}

    response = analyze(client, "東京")

    assert response.json()["grammar"] == []


def test_cached_sentence_returns_same_grammar(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "grammar": [
            {"start_token_id": 1, "end_token_id": 1, "name": "주제 は", "explanation_ko": "주제"}
        ],
    }
    first = analyze(client, "私は学生です。")

    second = analyze(client, "私は学生です。")

    assert second.json() == first.json()
    assert len(fake_llm.requests) == 1


@pytest.mark.parametrize(
    "grammar",
    [
        [{"start_token_id": 0, "end_token_id": 4, "name": "범위 밖", "explanation_ko": "설명"}],
        [{"start_token_id": -1, "end_token_id": 0, "name": "음수", "explanation_ko": "설명"}],
        [{"start_token_id": 2, "end_token_id": 1, "name": "거꾸로", "explanation_ko": "설명"}],
        [{"start_token_id": 1, "end_token_id": 1, "name": "", "explanation_ko": "설명"}],
        [{"start_token_id": 1, "end_token_id": 1, "name": "이름", "explanation_ko": " "}],
        [{"start_token_id": "1", "end_token_id": 1, "name": "이름", "explanation_ko": "설명"}],
        [{"start_token_id": True, "end_token_id": 1, "name": "이름", "explanation_ko": "설명"}],
        # 숫자가 없는 문장에 없는 자리표시자를 쓴 이름·설명
        [{"start_token_id": 1, "end_token_id": 1, "name": "⟨N1⟩", "explanation_ko": "설명"}],
        [{"start_token_id": 1, "end_token_id": 1, "name": "이름", "explanation_ko": "⟨N0⟩"}],
        ["not an object"],
        "not a list",
        None,
    ],
)
def test_invalid_grammar_fails_the_sentence_and_is_not_stored(client, fake_llm, grammar):
    # 토큰은 0~3 네 개다.
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "grammar": grammar}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert SentenceAnalysis.objects.count() == 0


@pytest.mark.parametrize(
    ("sentence", "name", "explanation"),
    [
        ("私は学生です。", "주제 は", "私は学生です에서 は는 주제"),
        ("私は学生です。", "私は学生です의 は", "주제"),
        # LLM은 숫자 대신 자리표시자가 든 문장을 본다.
        ("私は3人です。", "주제 は", "私は⟨N1⟩人です에서 は는 주제"),
    ],
)
def test_grammar_text_quoting_whole_sentence_fails_and_is_not_stored(
    client, fake_llm, sentence, name, explanation
):
    # 공용 테이블에 원문이 들어가지 않게, 문장 전체를 인용한 이름·설명은 받지 않는다.
    fake_llm.response = {
        "translation_ko": "번역 ⟨N1⟩" if "3" in sentence else "번역",
        "grammar": [
            {"start_token_id": 1, "end_token_id": 1, "name": name, "explanation_ko": explanation}
        ],
    }

    response = analyze(client, sentence)

    assert response.status_code == 502
    assert SentenceAnalysis.objects.count() == 0


def test_grammar_spanning_whole_sentence_may_not_quote_it(client, fake_llm):
    # 구간이 문장 전체여도 여러 토큰이면 원문을 옮긴 것이다. 토큰: 0 私 / 1 は / 2 学生 / 3 です
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "grammar": [
            {
                "start_token_id": 0,
                "end_token_id": 3,
                "name": "문장",
                "explanation_ko": "私は学生です에서 は는 주제",
            }
        ],
    }

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert SentenceAnalysis.objects.count() == 0


def test_grammar_text_may_quote_sentence_that_is_the_grammar_span_itself(client, fake_llm):
    # 문법 구간이 곧 문장 전체면 그 구간 글자를 인용할 수밖에 없다. 토큰: 0 です
    fake_llm.response = {
        "translation_ko": "입니다",
        "grammar": [
            {
                "start_token_id": 0,
                "end_token_id": 0,
                "name": "정중 です",
                "explanation_ko": "です는 정중",
            }
        ],
    }

    response = analyze(client, "です")

    assert response.status_code == 200
    assert response.json()["grammar"][0]["explanation_ko"] == "です는 정중"


def test_llm_response_without_grammar_fails(client, fake_llm):
    fake_llm.fill_defaults = False
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "words": []}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502


def test_llm_response_without_words_fails(client, fake_llm):
    fake_llm.fill_defaults = False
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "grammar": []}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert SentenceAnalysis.objects.count() == 0


def _word(token_id=2, lemma="学生", reading="がくせい", meaning_ko="학생"):
    return {"token_id": token_id, "lemma": lemma, "reading": reading, "meaning_ko": meaning_ko}


@pytest.mark.parametrize(
    "words",
    [
        [_word(token_id=4)],  # 범위 밖
        [_word(token_id=-1)],
        [_word(token_id="2")],
        [_word(token_id=True)],
        [_word(lemma="")],
        [_word(reading=" ")],
        [_word(meaning_ko="")],
        # 읽기는 가나(와 장음)로만 쓴다.
        [_word(reading="gakusei")],
        [_word(reading="学生")],
        [_word(reading="がく生")],
        [_word(reading="학생")],
        [_word(reading="・")],  # 가타카나 블록의 문장부호는 가나가 아니다
        [_word(reading="゠")],
        [_word(reading="ー")],  # 가나 없이 장음만
        [_word(meaning_ko="⟨N1⟩명")],  # 숫자가 없는 문장의 자리표시자
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

    assert response.status_code == 502
    assert SentenceAnalysis.objects.count() == 0


def test_word_meaning_quoting_whole_sentence_fails_and_is_not_stored(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "words": [_word(meaning_ko="私は学生です에서 학생")],
    }

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert SentenceAnalysis.objects.count() == 0


@pytest.mark.parametrize(
    ("sentence", "translation", "dropped", "kept"),
    [
        # 숫자만 있는 토큰. 토큰: 0 3 / 1 人 / 2 で / 3 行く
        (
            "3人で行く",
            "⟨N1⟩명이서 간다",
            _word(0, "⟨N1⟩", "⟨N1⟩", "⟨N1⟩"),
            _word(3, "行く", "いく", "가다"),
        ),
        # 숫자가 섞인 토큰. LLM이 사전형에 숫자를 지어내면 다른 숫자 문장에 잘못 재사용된다.
        # 토큰: 0 X1 / 1 2 / 2 を / 3 買う
        (
            "X12を買う",
            "X⟨N1⟩를 산다",
            _word(0, "X1", "えっくすいち", "X1"),
            _word(3, "買う", "かう", "사다"),
        ),
        # 기호 토큰. 토큰: 0 行く / 1 ！
        ("行く！", "간다!", _word(1, "！", "！", "느낌표"), _word(0, "行く", "いく", "가다")),
        # 숫자열 뒤쪽 토큰(키 텍스트에서 빈 조각). 토큰: 0 X1 / 1 2 / 2 を / 3 買う
        ("X12を買う", "X⟨N1⟩를 산다", _word(1, "2", "に", "2"), _word(3, "買う", "かう", "사다")),
        # 조사·조동사는 단어가 아니라 문법이다. 토큰: 0 私 / 1 は / 2 学生 / 3 です
        ("私は学生です。", "나는 학생입니다.", _word(1, "は", "は", "주제"), _word(2)),
        ("私は学生です。", "나는 학생입니다.", _word(3, "です", "です", "이다"), _word(2)),
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
        "words": [_word(2, meaning_ko="학생"), _word(2, meaning_ko="생도")],
    }

    response = analyze(client, "私は学生です。")

    assert [word["meaning_ko"] for word in response.json()["words"]] == ["학생"]


def test_word_meaning_quoting_whole_sentence_with_spaces_fails(client, fake_llm):
    # 형태소 사이에 공백을 넣어 인용해도 원문을 옮긴 것이다.
    fake_llm.response = {
        "translation_ko": "나는 학생입니다.",
        "words": [_word(meaning_ko="私 は 学生 です에서 학생")],
    }

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert SentenceAnalysis.objects.count() == 0


def test_katakana_reading_of_loanword_is_kept_as_is(client, fake_llm):
    # 외래어(사전에 없는 새 말 포함)의 가타카나 읽기는 히라가나로 바꾸지 않는다.
    # 토큰: 0 コーヒー / 1 を / 2 飲む
    fake_llm.response = {
        "translation_ko": "커피를 마신다",
        "words": [_word(0, "コーヒー", "コーヒー", "커피"), _word(2, "飲む", "のむ", "마시다")],
    }

    response = analyze(client, "コーヒーを飲む")

    assert [word["reading"] for word in response.json()["words"]] == ["コーヒー", "のむ"]


def test_cached_sentence_returns_same_words(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "words": [_word()]}
    first = analyze(client, "私は学生です。")

    second = analyze(client, "私は学生です。")

    assert second.json()["words"] == first.json()["words"]
    assert len(second.json()["words"]) == 1
    assert len(fake_llm.requests) == 1


def test_reused_words_point_at_same_characters_and_restore_numbers(client, fake_llm):
    # 토큰: 0 3 / 1 人 / 2 で / 3 行く
    fake_llm.response = {
        "translation_ko": "⟨N1⟩명이서 간다",
        "words": [_word(token_id=3, lemma="行く", reading="いく", meaning_ko="가다")]
        + [_word(token_id=1, lemma="人", reading="にん", meaning_ko="⟨N1⟩명의 명")],
    }
    analyze(client, "3人で行く")

    response = analyze(client, "  「12人で行く。」")

    words = response.json()["words"]
    assert [(word["start"], word["end"]) for word in words] == [(7, 9), (5, 6)]
    assert words[1]["meaning_ko"] == "12명의 명"
    assert len(fake_llm.requests) == 1


def test_same_sentence_is_reused_without_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    analyze(client, "私は学生です。")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json()["translation_ko"] == "나는 학생입니다."
    assert len(fake_llm.requests) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("私は学生です。", "私は学生です"),  # 끝 기호
        ("私は学生です", "  私は学生です "),  # 앞뒤 공백
        ("私は学生です", "私は　学生 です"),  # 일본어 사이 공백
        ("私は学生です", "「私は学生です。」"),  # 문장을 감싼 괄호
        ("ABCは学生です", "ＡＢＣは学生です"),  # 전각 영숫자
        ("ガクセイです", "ｶﾞｸｾｲです"),  # 반각 가나
        ("あれ", "あれ〜"),  # 물결표
        ("あれ", "あれ~"),
        ("I love Tokyoです", "I  love Tokyoです"),  # 영어 단어 사이 공백은 하나로
        ("私は学生です", "私は\u200b学生です"),  # 제로 폭 공백
        ("私は学生です", "\ufeff私は学生です"),  # BOM
        ("が好き", "か\u3099好き"),  # 결합 문자로 쓴 탁점
        ("한국は好き", "한국は好き"),  # 분해형 한글(결합 등급 0)
    ],
)
def test_sentences_differing_only_in_notation_reuse_analysis(client, fake_llm, first, second):
    analyze(client, first)

    response = analyze(client, second)

    assert response.status_code == 200
    assert len(fake_llm.requests) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("行こう", "行こう？"),  # 뜻을 바꾸는 기호는 남긴다
        ("行こう", "行こう！"),
        ("行こう", "行こう…"),
        ("I love Tokyoです", "Ilove Tokyoです"),
        ("x2", "x²"),  # 폭 통일만 한다(NFKC 호환 분해 금지)
    ],
)
def test_sentences_differing_in_meaning_are_analyzed_separately(client, fake_llm, first, second):
    analyze(client, first)

    analyze(client, second)

    assert len(fake_llm.requests) == 2


def test_sentences_differing_only_in_numbers_reuse_analysis(client, fake_llm):
    fake_llm.response = {"translation_ko": "⟨N1⟩명이서 ⟨N2⟩시에 간다."}
    first = analyze(client, "3人で10時に行く。")

    second = analyze(client, "5人で7時に行く。")

    assert first.json()["translation_ko"] == "3명이서 10시에 간다."
    assert second.json()["translation_ko"] == "5명이서 7시에 간다."
    assert len(fake_llm.requests) == 1


def test_particle_after_number_follows_restored_number(client, fake_llm):
    # 1(일)과 2(이)는 같은 캐시를 쓰지만 뒤따르는 조사는 숫자 발음에 따라 다르다.
    fake_llm.response = {"translation_ko": "⟨N1⟩는 맞다"}

    first = analyze(client, "1は正しい")
    second = analyze(client, "2は正しい")

    assert first.json()["translation_ko"] == "1은 맞다"
    assert second.json()["translation_ko"] == "2는 맞다"


@pytest.mark.parametrize(
    ("sentence", "translation", "restored"),
    [
        ("3を選ぶ", "⟨N1⟩를 고른다", "3을 고른다"),  # 삼
        ("4が出た", "⟨N1⟩이 나왔다", "4가 나왔다"),  # 사
        ("6と7", "⟨N1⟩와 ⟨N2⟩", "6과 7"),  # 육
        ("10は多い", "⟨N1⟩는 많다", "10은 많다"),  # 십
        ("20000は多い", "⟨N1⟩는 많다", "20000은 많다"),  # 이만
        ("1で割る", "⟨N1⟩으로 나눈다", "1로 나눈다"),  # 일: ㄹ 받침은 '로'
        ("3で割る", "⟨N1⟩로 나눈다", "3으로 나눈다"),
        ("2で割る", "⟨N1⟩으로는 부족", "2로는 부족"),
        ("3としては", "⟨N1⟩로서는", "3으로서는"),  # (으)로 뒤에 조사가 겹친다
        ("1からは", "⟨N1⟩으로부터는", "1로부터는"),
        ("3でも", "⟨N1⟩로도", "3으로도"),
        ("2は？", "⟨N1⟩은요?", "2는요?"),  # 조사 뒤에 요가 붙는다
        ("1は？", "⟨N1⟩는요?", "1은요?"),
        ("1種類", "⟨N1⟩가지", "1가지"),  # 조사가 아닌 말은 그대로
        ("第2課", "제⟨N1⟩과", "제2과"),  # 원문에서 숫자 뒤가 조사가 아니면 그대로(課)
        ("2課と3課", "⟨N1⟩과와 ⟨N2⟩과", "2과와 3과"),
    ],
)
def test_particle_is_fixed_for_each_number(client, fake_llm, sentence, translation, restored):
    fake_llm.response = {"translation_ko": translation}

    response = analyze(client, sentence)

    assert response.json()["translation_ko"] == restored


def test_numbers_are_not_sent_to_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "⟨N1⟩명이서 간다."}

    analyze(client, "３人で行く")

    [request] = fake_llm.requests
    assert request["sentence"] == "⟨N1⟩人で行く"
    assert [token["surface"] for token in request["tokens"]] == ["⟨N1⟩", "人", "で", "行く"]


@pytest.mark.parametrize(
    ("sentence", "key_text", "translation", "restored"),
    [
        ("1.5倍", "⟨N1⟩.⟨N2⟩倍", "⟨N1⟩.⟨N2⟩배", "1.5배"),  # 소수점
        ("-3度", "-⟨N1⟩度", "-⟨N1⟩도", "-3도"),  # 부호
        ("10:30に", "⟨N1⟩:⟨N2⟩に", "⟨N1⟩:⟨N2⟩에", "10:30에"),  # 시각
        ("10/18に", "⟨N1⟩/⟨N2⟩に", "⟨N1⟩/⟨N2⟩에", "10/18에"),  # 날짜
        ("3〜5人", "⟨N1⟩〜⟨N2⟩人", "⟨N1⟩~⟨N2⟩명", "3~5명"),  # 범위
    ],
)
def test_symbols_inside_numbers_are_kept(
    client, fake_llm, sentence, key_text, translation, restored
):
    fake_llm.response = {"translation_ko": translation}

    response = analyze(client, sentence)

    assert fake_llm.requests[0]["sentence"] == key_text
    assert response.json()["translation_ko"] == restored


@pytest.mark.parametrize(
    ("sentence", "key_text"),
    [
        ("3人〜5人", "⟨N1⟩人〜⟨N2⟩人"),  # 조수사가 붙은 범위
        ("10時〜12時", "⟨N1⟩時〜⟨N2⟩時"),
        ("三〜五人", "三〜五人"),  # 한자 숫자 범위
        ("-5〜-3℃", "-⟨N1⟩〜-⟨N2⟩℃"),  # 끝점이 부호로 시작
        ("¥300〜¥500", "¥⟨N1⟩〜¥⟨N2⟩"),  # 끝점이 통화 기호로 시작
        ("そうだね〜3人で", "そうだね⟨N1⟩人で"),  # 앞에 숫자가 없으면 늘인 말투로 본다
        ("3回だよ〜5人で", "⟨N1⟩回だよ⟨N2⟩人で"),  # 숫자가 앞 3글자보다 멀다
    ],
)
def test_tilde_is_kept_only_in_number_ranges(client, fake_llm, sentence, key_text):
    analyze(client, sentence)

    assert fake_llm.requests[0]["sentence"] == key_text


@pytest.mark.parametrize(
    ("sentence", "key_text", "translation", "restored"),
    [
        ("50%増", "⟨N1⟩%増", "⟨N1⟩% 증가", "50% 증가"),  # 숫자 뒤 단위 기호
        ("36.5℃", "⟨N1⟩.⟨N2⟩℃", "⟨N1⟩.⟨N2⟩℃", "36.5℃"),
        ("¥500です", "¥⟨N1⟩です", "¥⟨N1⟩입니다", "¥500입니다"),  # 숫자 앞 통화 기호
    ],
)
def test_unit_and_currency_symbols_next_to_numbers_are_kept(
    client, fake_llm, sentence, key_text, translation, restored
):
    fake_llm.response = {"translation_ko": translation}

    response = analyze(client, sentence)

    assert fake_llm.requests[0]["sentence"] == key_text
    assert response.json()["translation_ko"] == restored


@pytest.mark.parametrize(
    "sentence",
    [
        "五％の人",
        "￥五百です",
        "三/五の人",
        "三.五倍",
        "零％の人",
        "零〜五人",
        "一億/二億",
        "一兆％増",
    ],
)
def test_symbols_next_to_kanji_numerals_are_kept(client, fake_llm, sentence):
    analyze(client, sentence)

    assert fake_llm.requests[0]["sentence"] == sentence


@pytest.mark.parametrize(("sentence", "key_text"), [("-三度", "-三度"), ("+五人", "+五人")])
def test_sign_before_kanji_numeral_is_kept(client, fake_llm, sentence, key_text):
    analyze(client, sentence)

    assert fake_llm.requests[0]["sentence"] == key_text


@pytest.mark.parametrize(
    ("first", "first_translation", "second"),
    [
        ("1.5倍", "⟨N1⟩.⟨N2⟩배", "15倍"),
        ("-3度", "-⟨N1⟩도", "3度"),
        ("10:30", "⟨N1⟩:⟨N2⟩", "1030"),
        ("3〜5人", "⟨N1⟩~⟨N2⟩명", "35人"),
        ("50%", "⟨N1⟩%", "50"),
        ("¥500", "¥⟨N1⟩", "500"),
    ],
)
def test_numbers_differing_in_symbols_are_analyzed_separately(
    client, fake_llm, first, first_translation, second
):
    fake_llm.response = {"translation_ko": first_translation}
    assert analyze(client, first).status_code == 200

    analyze(client, second)

    assert len(fake_llm.requests) == 2


def test_kanji_numerals_are_kept(client, fake_llm):
    analyze(client, "二枚目の皿")

    [request] = fake_llm.requests
    assert request["sentence"] == "二枚目の皿"


@pytest.mark.parametrize("translation", ["세 명이서 간다.", "⟨N2⟩명이서 간다."])
def test_translation_missing_placeholder_fails_and_is_not_stored(client, fake_llm, translation):
    fake_llm.response = {"translation_ko": translation}

    response = analyze(client, "3人で行く")

    assert response.status_code == 502
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    fake_llm.response = {"translation_ko": "⟨N1⟩명이서 간다."}
    assert analyze(client, "3人で行く").json()["translation_ko"] == "3명이서 간다."
    assert len(fake_llm.requests) == 2


def test_stored_analysis_has_no_original_text_or_numbers(client, fake_llm):
    # 토큰: 0 私 / 1 は / 2 3 / 3 人 / 4 で / 5 行く
    fake_llm.response = {
        "translation_ko": "나는 ⟨N1⟩명이서 간다.",
        "grammar": [
            {"start_token_id": 2, "end_token_id": 4, "name": "인원 で", "explanation_ko": "설명"}
        ],
    }

    analyze(client, "私は3人で行く。")

    [row] = SentenceAnalysis.objects.values()
    # 원문을 담을 칸이 없고, 번역은 숫자 대신 자리표시자로 저장한다.
    assert set(row) == {
        "draft_analysis",
        "id",
        "sentence_hash",
        "normalize_version",
        "normalized_length",
        "status",
        "translation_ko",
        "created_at",
        "updated_at",
    }
    assert row["translation_ko"] == "나는 ⟨N1⟩명이서 간다."
    assert row["status"] == "complete"
    assert row["normalized_length"] == len("私は⟨N1⟩人で行く")
    # 문법 항목에는 키 텍스트 위치와 LLM이 쓴 이름·설명만 있다(⟨N1⟩人で = 2~8).
    assert row["draft_analysis"] == {
        "grammar": [{"start": 2, "end": 8, "name": "인원 で", "explanation_ko": "설명"}],
        "words": [],
    }


def test_first_saved_analysis_wins_when_same_sentence_is_saved_concurrently(client, fake_llm):
    # 첫 요청이 LLM 응답을 기다리는 사이에 같은 문장의 다른 요청이 먼저 저장한다.
    def other_request_saves_first():
        fake_llm.response = {"translation_ko": "먼저 저장된 번역"}
        analyze(Client(), "私は学生です。")
        fake_llm.response = {"translation_ko": "늦게 끝난 번역"}

    fake_llm.before_respond = other_request_saves_first

    response = analyze(client, "私は学生です。")

    assert response.json()["translation_ko"] == "먼저 저장된 번역"
    assert SentenceAnalysis.objects.count() == 1


def test_first_filled_grammar_wins_when_row_without_grammar_is_filled_concurrently(
    client, fake_llm, monkeypatch
):
    # 임시 분석을 받기 전에 저장된 행(draft_analysis NULL)을 두 요청이 함께 다시 분석한다.
    fake_llm.response = {"translation_ko": "옛 번역"}
    analyze(client, "私は学生です。")
    SentenceAnalysis.objects.update(draft_analysis=None)

    # 늦은 요청이 NULL인 행을 읽은 직후, 채우기 전에 다른 요청이 먼저 채운다.
    get_or_create = SentenceAnalysis.objects.get_or_create

    def other_request_fills_after_read(**kwargs):
        monkeypatch.setattr(SentenceAnalysis.objects, "get_or_create", get_or_create)
        result = get_or_create(**kwargs)
        fake_llm.response = {"translation_ko": "먼저 채운 번역"}
        analyze(Client(), "私は学生です。")
        return result

    fake_llm.response = {"translation_ko": "늦게 끝난 번역"}
    monkeypatch.setattr(SentenceAnalysis.objects, "get_or_create", other_request_fills_after_read)

    response = analyze(client, "私は学生です。")

    assert response.json()["translation_ko"] == "먼저 채운 번역"
    assert SentenceAnalysis.objects.get().translation_ko == "먼저 채운 번역"


@pytest.mark.parametrize(
    "llm_response",
    [
        {"translation_ko": ""},
        {"translation_ko": "   "},
        {"translation_ko": 3},
        {},
        "not an object",
    ],
)
def test_invalid_llm_response_fails_the_sentence(client, fake_llm, llm_response):
    fake_llm.response = llm_response

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert response.json() == {"error": "ANALYSIS:FAILED"}


def test_sentence_too_long_for_morphology_fails_without_calling_llm(client, fake_llm):
    # SudachiPy는 49,149바이트를 넘는 입력을 나누지 못한다.
    response = analyze(client, "あ" * 20000)

    assert response.status_code == 502
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert fake_llm.requests == []


def test_llm_error_fails_the_sentence(client, fake_llm):
    # LLM 클라이언트는 타임아웃 등 외부 실패를 ANALYSIS:FAILED로 알린다(test_llm_client).
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 0


def test_unexpected_error_is_not_hidden_as_analysis_failure(client, fake_llm):
    # 외부 실패가 아닌 예외(우리 코드의 버그)는 502로 숨기지 않고 그대로 드러낸다.
    fake_llm.error = TypeError("bug")

    with pytest.raises(TypeError):
        analyze(client, "私は学生です。")


def test_text_with_lone_surrogate_is_rejected_without_calling_llm(client, fake_llm):
    # JSON에는 들어올 수 있지만 UTF-8로 인코딩할 수 없는 문자
    response = client.post(
        "/api/analyses/", '{"text": "\\ud800です"}', content_type="application/json"
    )

    assert response.status_code == 400
    assert response.json() == {"error": "ANALYSIS:TEXT_REQUIRED"}
    assert fake_llm.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "  "},
        {"text": 3},
        ["私は学生です。"],
        {"text": "。」"},
        {"text": "\u200b"},
    ],
)
def test_missing_text_is_rejected_without_calling_llm(client, fake_llm, body):
    response = client.post("/api/analyses/", body, content_type="application/json")

    assert response.status_code == 400
    assert response.json() == {"error": "ANALYSIS:TEXT_REQUIRED"}
    assert fake_llm.requests == []


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_all_succeed(fake_llm):
    # runserver·gunicorn 스레드처럼 여러 요청이 동시에 형태소 분석을 한다.
    long_sentence = "吾輩は猫である。名前はまだ無い。" * 200
    statuses = []

    def send_requests():
        thread_client = Client()
        try:
            for _ in range(10):
                statuses.append(analyze(thread_client, long_sentence).status_code)
        finally:
            # 스레드가 연 DB 연결을 닫아야 테스트 DB를 지울 수 있다.
            connection.close()

    threads = [threading.Thread(target=send_requests) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses == [200] * 80


def test_llm_receives_sentence_and_token_ids(client, fake_llm):
    analyze(client, "私は学生です。")

    [request] = fake_llm.requests
    # LLM에는 정규화한 키 텍스트를 보낸다.
    assert request["sentence"] == "私は学生です"
    assert request["tokens"] == [
        {"id": 0, "surface": "私"},
        {"id": 1, "surface": "は"},
        {"id": 2, "surface": "学生"},
        {"id": 3, "surface": "です"},
    ]
