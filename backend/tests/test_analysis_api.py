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
    assert response.json() == {"translation_ko": "나는 학생입니다."}


def test_same_sentence_is_reused_without_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    analyze(client, "私は学生です。")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json() == {"translation_ko": "나는 학생입니다."}
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

    assert first.json() == {"translation_ko": "3명이서 10시에 간다."}
    assert second.json() == {"translation_ko": "5명이서 7시에 간다."}
    assert len(fake_llm.requests) == 1


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
    assert response.json() == {"translation_ko": restored}


@pytest.mark.parametrize(
    ("first", "first_translation", "second"),
    [
        ("1.5倍", "⟨N1⟩.⟨N2⟩배", "15倍"),
        ("-3度", "-⟨N1⟩도", "3度"),
        ("10:30", "⟨N1⟩:⟨N2⟩", "1030"),
        ("3〜5人", "⟨N1⟩~⟨N2⟩명", "35人"),
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
    assert analyze(client, "3人で行く").json() == {"translation_ko": "3명이서 간다."}
    assert len(fake_llm.requests) == 2


def test_stored_analysis_has_no_original_text_or_numbers(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 ⟨N1⟩명이서 간다."}

    analyze(client, "私は3人で行く。")

    [row] = SentenceAnalysis.objects.values()
    # 원문을 담을 칸이 없고, 번역은 숫자 대신 자리표시자로 저장한다.
    assert set(row) == {
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


def test_first_saved_analysis_wins_when_same_sentence_is_saved_concurrently(client, fake_llm):
    # 첫 요청이 LLM 응답을 기다리는 사이에 같은 문장의 다른 요청이 먼저 저장한다.
    def other_request_saves_first():
        fake_llm.response = {"translation_ko": "먼저 저장된 번역"}
        analyze(Client(), "私は学生です。")
        fake_llm.response = {"translation_ko": "늦게 끝난 번역"}

    fake_llm.before_respond = other_request_saves_first

    response = analyze(client, "私は学生です。")

    assert response.json() == {"translation_ko": "먼저 저장된 번역"}
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


def test_llm_error_fails_the_sentence(client, fake_llm):
    fake_llm.error = RuntimeError("timeout")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 502
    assert response.json() == {"error": "analysis_failed"}


@pytest.mark.parametrize(
    "body",
    [{}, {"text": ""}, {"text": "  "}, {"text": 3}, ["私は学生です。"], {"text": "。」"}],
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
