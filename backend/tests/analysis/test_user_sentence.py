"""분석한 문장을 내 기록(user_sentence)에 저장하기(#93)."""

import hashlib

import pytest
from django.apps import apps
from django.contrib import admin
from django.core import serializers
from django.db import DataError

from analysis import patterns
from analysis.models import SentenceAnalysis, UserSentence
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, connected_client, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_new_sentence_is_recorded_for_the_user(client, analyst, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}

    analyze(client, "走っている")

    row = UserSentence.objects.get()
    assert row.user == analyst
    assert row.original_text == "走っている"
    assert row.original_hash == sha256("走っている")
    assert row.analysis == SentenceAnalysis.objects.get()


def test_original_before_normalization_is_recorded(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}

    analyze(client, " 「走っている」")

    row = UserSentence.objects.get()
    assert row.original_text == " 「走っている」"
    assert row.original_hash == sha256(" 「走っている」")


def test_cached_sentence_updates_the_same_record(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")
    first = UserSentence.objects.get()

    response = analyze(client, "走っている")

    assert response.types() == ["translation", "analysis"]
    row = UserSentence.objects.get()
    assert row.pk == first.pk
    assert row.created_at == first.created_at
    assert row.last_analyzed_at > first.last_analyzed_at


def test_rematched_sentence_is_recorded(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")
    UserSentence.objects.all().delete()
    patterns.raise_pattern_set_version()

    analyze(client, "走っている")

    assert UserSentence.objects.get().analysis == SentenceAnalysis.objects.get()


def test_rematched_and_judged_sentence_is_recorded(client, fake_llm):
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, "彼が来ている")
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}
    analyze(client, "走っている")
    UserSentence.objects.all().delete()
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}

    analyze(client, "彼が来ている")

    assert len(fake_llm.rematch_requests) == 1
    assert UserSentence.objects.get().original_text == "彼が来ている"


def test_stale_sentence_reanalyzed_by_llm_updates_the_record(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")
    first = UserSentence.objects.get()
    SentenceAnalysis.objects.update(is_stale=True)

    analyze(client, "走っている")

    assert len(fake_llm.requests) == 2
    row = UserSentence.objects.get()
    assert row.last_analyzed_at > first.last_analyzed_at


def test_original_differing_only_in_numbers_is_recorded_separately(client, fake_llm):
    fake_llm.response = {"translation_ko": "⟨N1⟩명이서"}

    analyze(client, "1人で")
    analyze(client, "2人で")

    assert SentenceAnalysis.objects.count() == 1
    assert sorted(UserSentence.objects.values_list("original_text", flat=True)) == [
        "1人で",
        "2人で",
    ]


def test_each_user_has_own_record(client, analyst, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")
    mine = UserSentence.objects.get(user=analyst)

    analyze(connected_client("other"), "走っている")

    assert UserSentence.objects.count() == 2
    assert UserSentence.objects.get(user=analyst).last_analyzed_at == mine.last_analyzed_at


def test_failed_analysis_neither_creates_nor_updates_record(client, fake_llm):
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, "走っている")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert not UserSentence.objects.exists()

    fake_llm.error = None
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")
    first = UserSentence.objects.get()
    SentenceAnalysis.objects.update(is_stale=True)
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    analyze(client, "走っている")

    assert UserSentence.objects.get().last_analyzed_at == first.last_analyzed_at


def test_record_is_deleted_with_its_user(client, analyst, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")

    analyst.delete()

    assert not UserSentence.objects.exists()


def test_record_is_not_in_django_admin():
    assert not admin.site.is_registered(UserSentence)


def test_name_readings_are_private_and_cache_hits_fill_older_records(client, analyst, fake_llm):
    fake_llm.response = {
        "translation_ko": "왔다",
        "name_spans": [{"token_ids": [0], "type": "person"}],
    }
    analyze(client, "西山さんが来た")
    mine = UserSentence.objects.get(user=analyst)
    expected = [{"start": 0, "end": 2, "reading": "にしやま", "reading_ko": "니시야마"}]
    assert mine.name_readings == expected
    assert "니시야마" not in serializers.serialize("json", SentenceAnalysis.objects.all())

    UserSentence.objects.filter(pk=mine.pk).update(name_readings=[])
    fake_llm.forget_requests()
    analyze(client, "西山さんが来た")
    mine.refresh_from_db()
    assert mine.name_readings == expected
    saved_at = mine.last_analyzed_at

    other = connected_client("other")
    analyze(other, "  西山さんが来た")
    assert fake_llm.all_requests() == []
    other_row = UserSentence.objects.exclude(user=analyst).get()
    assert other_row.name_readings == [{**expected[0], "start": 2, "end": 4}]
    mine.refresh_from_db()
    assert mine.name_readings == expected
    assert mine.last_analyzed_at == saved_at


@pytest.mark.parametrize("judging", [False, True])
def test_rematch_preserves_name_readings(client, fake_llm, judging):
    fake_llm.response = {
        "translation_ko": "니시야마 씨가 와 있다",
        "name_spans": [{"token_ids": [0], "type": "person"}],
    }
    analyze(client, "西山さんが来ている")
    row = UserSentence.objects.get()
    expected = row.name_readings
    assert expected
    if judging:
        fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}
        analyze(client, "走っている")
        fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    else:
        patterns.raise_pattern_set_version()
    UserSentence.objects.filter(pk=row.pk).update(name_readings=[])

    analyze(client, "西山さんが来ている")

    row.refresh_from_db()
    assert row.name_readings == expected
    assert len(fake_llm.rematch_requests) == int(judging)


def test_reanalysis_clears_readings_when_a_name_is_no_longer_detected(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "하루가 왔다",
        "name_spans": [{"token_ids": [0], "type": "person"}],
    }
    analyze(client, "春が来た")
    assert UserSentence.objects.get().name_readings
    SentenceAnalysis.objects.update(is_stale=True)
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": []}

    response = analyze(client, "春が来た")

    previous = next(event for event in response.events if event["type"] == "previous")
    assert previous["words"][0]["reading_ko"] == "하루"
    assert UserSentence.objects.get().name_readings == []


def test_original_is_stored_only_in_user_sentence(client, fake_llm):
    # 원문 그대로가 키 텍스트가 되지 않게 감싼다. 예문은 LLM이 새로 쓴 문장이다.
    original = "「彼は走っている」"
    fake_llm.response = {
        "translation_ko": "그는 달리고 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"))],
    }

    analyze(client, original)

    for model in apps.get_models():
        if model is UserSentence:
            continue
        dumped = serializers.serialize("json", model.objects.all())
        assert original not in dumped, model
        assert "彼は走っている" not in dumped, model


def test_record_failure_keeps_the_response_and_logs_without_original(
    client, fake_llm, monkeypatch, caplog
):
    def fail(*args, **kwargs):
        raise DataError("走っている")

    monkeypatch.setattr(UserSentence.objects, "bulk_create", fail)
    fake_llm.response = {"translation_ko": "달리고 있다"}

    response = analyze(client, "走っている")

    assert response.types() == ["translation", "analysis"]
    assert response.json()["translation_ko"] == "달리고 있다"
    assert "분석 기록 저장 실패" in caplog.text
    assert "走っている" not in caplog.text
