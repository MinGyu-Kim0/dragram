"""사용자별 하루 토큰 한도와 동시 분석 요청 제한(#28, NFR-14)."""

import time
from contextlib import aclosing
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.utils import timezone

from analysis import jobs, limits, stream, words
from analysis.models import SentenceAnalysis, UsageLog
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, connected_client, post, span_answer
from tests.analysis.test_rematch import KITEIRU, cache_then_register_teiru

pytestmark = pytest.mark.django_db

TEXT = "雨が降る"


def spend(user, input_tokens, output_tokens, kind=UsageLog.Kind.LLM, created_at=None):
    """그 사용자의 LLM 사용 기록 하나를 남긴다."""
    fields = {"path": "llm"} if kind == UsageLog.Kind.REQUEST else {"purpose": "first_response"}
    row = UsageLog.objects.create(
        kind=kind,
        user=user,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        success=True,
        **fields,
    )
    if created_at is not None:
        UsageLog.objects.filter(pk=row.pk).update(created_at=created_at)


@pytest.fixture
def limited(settings, analyst):
    """하루 한도 100토큰을 다 쓴 analyst"""
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 100
    spend(analyst, 60, 40)


def test_today_tokens_sums_only_todays_llm_rows_of_that_user(analyst):
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    spend(analyst, 100, 20)
    spend(analyst, None, 7)
    spend(analyst, 1000, 1000, created_at=midnight - timedelta(minutes=1))
    spend(analyst, 1000, 1000, kind=UsageLog.Kind.REQUEST)
    spend(get_user_model().objects.create(username="other"), 1000, 1000)

    assert limits.today_tokens(analyst) == 127


def test_new_sentence_within_the_limit_is_analyzed(settings, client, fake_llm, analyst):
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 100
    spend(analyst, 60, 39)

    response = analyze(client, TEXT)

    assert response.status_code == 200
    assert "error" not in response.json()
    assert len(fake_llm.requests) == 1


def test_new_sentence_over_the_limit_is_refused_without_claiming(client, fake_llm, limited):
    response = analyze(client, TEXT)

    assert response.status_code == 429
    assert response.json()["error"] == "ANALYSIS:USAGE_LIMIT"
    assert fake_llm.all_requests() == []
    assert not SentenceAnalysis.objects.exists()


def test_stale_sentence_over_the_limit_is_refused_and_stays_unclaimed(
    settings, client, fake_llm, analyst
):
    analyze(client, TEXT)
    SentenceAnalysis.objects.update(is_stale=True)
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1
    fake_llm.forget_requests()

    response = analyze(client, TEXT)

    assert response.status_code == 429
    assert fake_llm.all_requests() == []
    assert SentenceAnalysis.objects.get().status != SentenceAnalysis.Status.PROCESSING


def test_cached_sentence_is_sent_over_the_limit(settings, client, fake_llm, analyst):
    analyze(client, TEXT)
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1
    fake_llm.forget_requests()

    response = analyze(client, TEXT)

    assert response.status_code == 200
    assert "error" not in response.json()
    assert fake_llm.all_requests() == []


def test_request_joining_a_running_job_is_not_refused(settings, client, fake_llm, monkeypatch):
    analyze(client, TEXT)
    SentenceAnalysis.objects.update(status="processing", word_spans=None)
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1
    monkeypatch.setattr(stream, "WAIT_SECONDS", 0.2)
    fake_llm.forget_requests()

    response = analyze(client, TEXT)

    # 처리 중인 작업에 붙어 기다린다. 소식이 오지 않아 대기 상한에서 닫힐 뿐이다.
    assert response.status_code == 200
    assert fake_llm.all_requests() == []


def test_rematch_over_the_limit_skips_the_judge_and_sends_the_fallback(
    settings, client, fake_llm, analyst
):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1

    response = analyze(client, KITEIRU)

    assert response.status_code == 200
    assert response.types() == ["translation", "analysis"]
    assert fake_llm.all_requests() == []
    # 다시 매칭한 것으로 기록하지 않아, 한도가 풀리면 다음 조회가 재판정한다.
    assert SentenceAnalysis.objects.get(translation_ko="그가 와 있다").span_matches.count() == 0


def active(user):
    """그 사용자의 동시 요청 셈"""
    with jobs._connection() as connection:
        return connection.zcard(limits._active_key(user))


@pytest.fixture
def no_active(analyst):
    """앞선 테스트 실행이 남긴 셈이 없게 한다."""
    with jobs._connection() as connection:
        connection.delete(limits._active_key(analyst))


def test_requests_over_the_concurrent_limit_are_refused_before_morphology(
    settings, client, fake_llm, analyst, no_active, monkeypatch
):
    settings.ANALYSIS_MAX_CONCURRENT = 2
    held = [limits.enter(analyst), limits.enter(analyst)]

    # 다른 사용자는 영향을 받지 않는다.
    assert analyze(connected_client("other"), TEXT).status_code == 200
    fake_llm.forget_requests()

    def no_morphology(text):
        raise AssertionError("형태소 분석을 부름")

    monkeypatch.setattr(words, "fixed_morphemes", no_morphology)
    response = analyze(client, "雪が降る")

    assert response.status_code == 429
    assert response.json()["error"] == "ANALYSIS:TOO_MANY_REQUESTS"
    assert fake_llm.all_requests() == []
    assert active(analyst) == 2
    for leave in held:
        leave()
    assert active(analyst) == 0


def test_finished_requests_leave_the_count(settings, client, fake_llm, analyst, no_active):
    settings.ANALYSIS_MAX_CONCURRENT = 1

    assert analyze(client, TEXT).status_code == 200  # LLM 스트림
    assert analyze(client, TEXT).status_code == 200  # 캐시
    assert analyze(client, "").status_code == 400  # 응답을 시작하기 전의 오류
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")
    assert analyze(client, "雪が降る").json()["error"] == "ANALYSIS:FAILED"  # 스트림 안의 오류

    assert active(analyst) == 0


def test_disconnected_stream_leaves_the_count(client, fake_llm, analyst, no_active):
    response = post(client, TEXT)
    assert active(analyst) == 1

    async def read_one_and_disconnect():
        # Django ASGI 처리기처럼 응답을 aclosing으로 읽다가 연결이 끊긴다.
        async with aclosing(aiter(response)) as content:
            await anext(content)

    async_to_sync(read_one_and_disconnect)()

    assert active(analyst) == 0


def test_count_left_by_a_dead_process_expires(settings, analyst, no_active, monkeypatch):
    settings.ANALYSIS_MAX_CONCURRENT = 1
    limits.enter(analyst)  # 빼지 못하고 죽은 요청
    with pytest.raises(BusinessError):
        limits.enter(analyst)

    now = time.time()
    monkeypatch.setattr(limits.time, "time", lambda: now + limits.ACTIVE_SECONDS + 1)

    limits.enter(analyst)
    assert active(analyst) == 1


def test_job_over_the_limit_at_start_fails_without_calling_the_llm(
    settings, client, fake_llm, analyst, monkeypatch
):
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 100
    enqueue = jobs.enqueue_analysis

    def enqueue_after_spending(*args):
        # 요청이 한도를 본 뒤, 작업이 시작되기 전에 다른 작업이 사용량을 채웠다.
        spend(analyst, 60, 40)
        enqueue(*args)

    monkeypatch.setattr(jobs, "enqueue_analysis", enqueue_after_spending)

    response = analyze(client, TEXT)

    assert response.json()["error"] == "ANALYSIS:USAGE_LIMIT"
    assert fake_llm.all_requests() == []
    assert SentenceAnalysis.objects.get().status == SentenceAnalysis.Status.FAILED
