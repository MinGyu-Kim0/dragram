"""분석 API: 같은 문장의 재사용, 저장되는 값, 동시 요청."""

import threading

import pytest
from django.db import connection

from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternMorpheme,
    SentenceAnalysis,
    SpanMatch,
)
from tests.analysis.helpers import analyze, connected_client, new_pattern

pytestmark = pytest.mark.django_db


def test_new_sentence_returns_translation(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json()["translation_ko"] == "나는 학생입니다."


def test_same_sentence_is_reused_without_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    analyze(client, "私は学生です。")

    fake_llm.forget_requests()

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json()["translation_ko"] == "나는 학생입니다."
    assert fake_llm.all_requests() == []


def test_stored_analysis_has_no_original_text_or_numbers(client, fake_llm):
    # 토큰: 0 私 / 1 は / 2 3 / 3 人 / 4 で / 5 走っ / 6 て / 7 いる
    fake_llm.response = {
        "translation_ko": "나는 ⟨N1⟩명이서 달리고 있다.",
        "new_patterns": [
            new_pattern(
                (3, "lemma"),
                (4, "lemma"),
                pattern_name="人で",
                usage_name="인원",
                explanation_ko="함께하는 사람 수를 나타낸다",
                example_ja="5人で来た",
            ),
            new_pattern((6, "lemma"), (7, "lemma")),
        ],
    }

    analyze(client, "私は3人で走っている。")

    [row] = SentenceAnalysis.objects.values()
    # 원문을 담을 칸이 없고, 번역은 숫자 대신 자리표시자로 저장한다.
    assert set(row) == {
        "word_spans",
        "sense_ids",
        "id",
        "sentence_hash",
        "normalize_version",
        "normalized_length",
        "status",
        "processing_started_at",
        "translation_ko",
        "pending_translation_ko",
        "is_stale",
        "generation",
        "matcher_version",
        "created_at",
        "updated_at",
    }
    assert row["translation_ko"] == "나는 ⟨N1⟩명이서 달리고 있다."
    assert row["status"] == "complete"
    assert row["normalized_length"] == len("私は⟨N1⟩人で走っている")
    assert (row["word_spans"], row["sense_ids"]) == ([], [])
    # 구간에는 키 텍스트 위치와 패턴·용법 ID만 있다(⟨N1⟩人で의 人で = 6~8, ている = 10~13).
    spans = SpanMatch.objects.order_by("start_offset").values(
        "start_offset", "end_offset", "state", "decided_by", "candidates"
    )
    assert list(spans) == [
        {
            "start_offset": 6,
            "end_offset": 8,
            "state": "decided",
            "decided_by": "llm",
            "candidates": None,
        },
        {
            "start_offset": 10,
            "end_offset": 13,
            "state": "decided",
            "decided_by": "llm",
            "candidates": None,
        },
    ]
    # 용법 설명은 LLM이 쓴 용법 일반 설명이고, 공용 예문은 LLM이 새로 쓴 예문뿐이다.
    assert list(
        GrammarUsage.objects.order_by("id").values_list("explanation_ko", "example_ja")
    ) == [
        ("함께하는 사람 수를 나타낸다", "5人で来た"),
        ("동작이 이어지고 있음을 나타낸다", "雨が降っている"),
    ]
    assert [p.test_cases for p in GrammarPattern.objects.order_by("id")] == [
        [{"text": "5人で来た", "should_match": True}],
        [{"text": "雨が降っている", "should_match": True}],
    ]
    # 어느 공용 테이블에도 원문이나 원문 숫자가 없다.
    for model in (SentenceAnalysis, SpanMatch, GrammarPattern, GrammarUsage, PatternMorpheme):
        for values in model.objects.values():
            stored = str(values)
            assert "私は" not in stored
            assert "走っている" not in stored
    assert not PatternMorpheme.objects.filter(lemma__contains="3").exists()


def test_first_filled_grammar_wins_when_row_without_grammar_is_filled_concurrently(
    client, fake_llm, monkeypatch
):
    # 단어 칸을 받기 전에 저장된 행(word_spans NULL)을 두 요청이 함께 다시 분석한다.
    fake_llm.response = {"translation_ko": "옛 번역"}
    analyze(client, "私は学生です。")
    SentenceAnalysis.objects.update(word_spans=None, sense_ids=None)

    # 늦은 요청이 NULL인 행을 읽은 직후, 채우기 전에 다른 요청이 먼저 채운다.
    get_or_create = SentenceAnalysis.objects.get_or_create

    def other_request_fills_after_read(**kwargs):
        monkeypatch.setattr(SentenceAnalysis.objects, "get_or_create", get_or_create)
        result = get_or_create(**kwargs)
        fake_llm.response = {"translation_ko": "먼저 채운 번역"}
        analyze(connected_client(), "私は学生です。")
        return result

    fake_llm.response = {"translation_ko": "늦게 끝난 번역"}
    monkeypatch.setattr(SentenceAnalysis.objects, "get_or_create", other_request_fills_after_read)

    response = analyze(client, "私は学生です。")

    assert response.json()["translation_ko"] == "먼저 채운 번역"
    assert SentenceAnalysis.objects.get().translation_ko == "먼저 채운 번역"


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_requests_all_succeed(fake_llm):
    # runserver·gunicorn 스레드처럼 여러 요청이 동시에 형태소 분석을 한다.
    long_sentence = "吾輩は猫である。名前はまだ無い。" * 200
    statuses = []

    def send_requests():
        thread_client = connected_client()
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
