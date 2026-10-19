import threading

import pytest
from django.db import connection
from django.test import Client

from analysis.models import SentenceAnalysis

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
    ],
)
def test_reused_grammar_points_at_same_characters_in_each_original(
    client, fake_llm, first, token_ranges, second, expected
):
    fake_llm.response = {"translation_ko": "번역 ⟨N1⟩" if "3" in first else "번역"}
    fake_llm.response["grammar"] = _grammar(*token_ranges)
    analyze(client, first)

    response = analyze(client, second)

    assert len(fake_llm.requests) == 1
    grammar = response.json()["grammar"]
    assert [(item["start"], item["end"]) for item in grammar] == expected


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


def test_llm_response_without_grammar_fails(client, fake_llm):
    fake_llm.fill_defaults = False
    fake_llm.response = {"translation_ko": "나는 학생입니다."}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502


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
    assert response.json() == {"error": "analysis_failed"}
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
        "draft_grammar",
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
    assert row["draft_grammar"] == [
        {"start": 2, "end": 8, "name": "인원 で", "explanation_ko": "설명"}
    ]


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
    assert response.json() == {"error": "analysis_failed"}


def test_sentence_too_long_for_morphology_fails_without_calling_llm(client, fake_llm):
    # SudachiPy는 49,149바이트를 넘는 입력을 나누지 못한다.
    response = analyze(client, "あ" * 20000)

    assert response.status_code == 502
    assert response.json() == {"error": "analysis_failed"}
    assert fake_llm.requests == []


def test_llm_error_fails_the_sentence(client, fake_llm):
    fake_llm.error = RuntimeError("timeout")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert response.json() == {"error": "analysis_failed"}


def test_text_with_lone_surrogate_is_rejected_without_calling_llm(client, fake_llm):
    # JSON에는 들어올 수 있지만 UTF-8로 인코딩할 수 없는 문자
    response = client.post(
        "/api/analyses/", '{"text": "\\ud800です"}', content_type="application/json"
    )

    assert response.status_code == 400
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
