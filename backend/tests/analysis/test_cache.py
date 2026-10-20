"""분석 API: 같은 문장의 재사용, 저장되는 값, 동시 요청."""

import threading

import pytest
from django.db import connection
from django.test import Client

from analysis.models import SentenceAnalysis
from tests.analysis.helpers import analyze

pytestmark = pytest.mark.django_db


def test_new_sentence_returns_translation(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json()["translation_ko"] == "나는 학생입니다."


def test_same_sentence_is_reused_without_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    analyze(client, "私は学生です。")

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json()["translation_ko"] == "나는 학생입니다."
    assert len(fake_llm.requests) == 1


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
