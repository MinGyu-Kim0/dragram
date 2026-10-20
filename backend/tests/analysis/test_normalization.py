"""분석 API: 표기만 다른 문장의 재사용과 정규화 규칙(기호·물결표·한자 숫자)."""

import pytest

from tests.analysis.helpers import analyze

pytestmark = pytest.mark.django_db


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
