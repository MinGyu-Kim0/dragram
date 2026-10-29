"""선점 만료와 시도 식별(#99). 작업자가 죽어 처리 중으로 남은 행은 만료 뒤 다음 요청이 다시
선점하고, 늦게 꺼낸 옛 작업은 새 시도의 행을 건드리지 못한다.
"""

from datetime import timedelta

import pytest
from django.db.models import F
from django.utils import timezone

from analysis import jobs, stream, worker
from analysis.models import SentenceAnalysis, UsageLog
from analysis.sentence import Sentence
from tests.analysis.helpers import analyze

pytestmark = pytest.mark.django_db

TEXT = "雨が降る"


def left_processing(seconds_ago, published=None):
    """작업자가 죽어 처리 중으로 남은 행. 처리 중 번역도 남아 있다. 준비 단계의 소식은 지운다."""
    if published is not None:
        published.clear()
    SentenceAnalysis.objects.update(
        status="processing",
        word_spans=None,
        processing_translation_ko="옛 번역",
        processing_started_at=timezone.now() - timedelta(seconds=seconds_ago),
    )
    return SentenceAnalysis.objects.get()


def reclaim(row):
    """다른 요청이 그 행을 다시 선점했다(새 시도)."""
    new_started = timezone.now()
    SentenceAnalysis.objects.filter(pk=row.pk).update(
        status="processing",
        processing_started_at=new_started,
        generation=F("generation") + 1,
        processing_translation_ko="새 시도 번역",
        word_spans=None,
    )
    return new_started


@pytest.fixture
def published(monkeypatch):
    """작업자가 보낸 소식"""
    messages = []
    monkeypatch.setattr(jobs, "publish", lambda sentence_hash, message: messages.append(message))
    return messages


def test_expired_processing_row_is_claimed_again_by_the_next_request(client, fake_llm):
    analyze(client, TEXT)
    old = left_processing(stream.CLAIM_EXPIRY_SECONDS + 1)
    fake_llm.forget_requests()

    response = analyze(client, TEXT)

    assert "error" not in response.json()
    assert len(fake_llm.requests) == 1
    row = SentenceAnalysis.objects.get()
    assert row.status == SentenceAnalysis.Status.COMPLETE
    assert row.generation == old.generation + 1
    assert row.processing_started_at > old.processing_started_at


def test_processing_row_within_the_expiry_is_only_waited_on(client, fake_llm):
    analyze(client, TEXT)
    old = left_processing(stream.CLAIM_EXPIRY_SECONDS - 10)
    fake_llm.forget_requests()

    response = analyze(client, TEXT)

    assert response.json()["error"] == "ANALYSIS:FAILED"  # 대기 상한
    assert fake_llm.all_requests() == []
    row = SentenceAnalysis.objects.get()
    assert (row.status, row.processing_started_at) == ("processing", old.processing_started_at)


def test_only_one_of_two_requests_claims_an_expired_row(client, fake_llm, analyst, monkeypatch):
    analyze(client, TEXT)
    left_processing(stream.CLAIM_EXPIRY_SECONDS + 1)
    queued = []
    monkeypatch.setattr(jobs, "enqueue_analysis", lambda *args: queued.append(args))

    states = [stream.claim(Sentence(TEXT), analyst)[0] for _ in range(2)]

    assert states == ["claimed", "processing"]
    assert len(queued) == 1


def test_queue_input_carries_the_claimed_attempt(client, fake_llm, analyst, monkeypatch):
    analyze(client, TEXT)
    left_processing(stream.CLAIM_EXPIRY_SECONDS + 1)
    queued = []
    monkeypatch.setattr(jobs, "enqueue_analysis", lambda *args: queued.append(args))

    stream.claim(Sentence(TEXT), analyst)

    [(_, text, _, started)] = queued
    assert text == TEXT
    assert started == SentenceAnalysis.objects.get().processing_started_at


def test_old_job_started_after_a_reclaim_does_nothing(client, fake_llm, published):
    analyze(client, TEXT)
    old = left_processing(stream.CLAIM_EXPIRY_SECONDS + 1, published)
    new_started = reclaim(old)
    usage = UsageLog.objects.filter(kind="request").latest("id")
    fake_llm.forget_requests()

    worker.run_analysis(old.pk, TEXT, usage.pk, old.processing_started_at)

    assert fake_llm.all_requests() == []
    assert published == []
    row = SentenceAnalysis.objects.get()
    assert (row.status, row.processing_started_at, row.processing_translation_ko) == (
        "processing",
        new_started,
        "새 시도 번역",
    )


@pytest.mark.parametrize("fails", [False, True])
def test_running_old_job_cannot_overwrite_the_new_attempt(client, fake_llm, published, fails):
    analyze(client, TEXT)
    old = left_processing(stream.CLAIM_EXPIRY_SECONDS + 1, published)
    usage = UsageLog.objects.filter(kind="request").latest("id")
    started = []
    fake_llm.before_respond = lambda: started.append(reclaim(old))
    if fails:
        fake_llm.response = "JSON이 아닌 응답"

    worker.run_analysis(old.pk, TEXT, usage.pk, old.processing_started_at)

    # 결과도, 처리 중 번역도, 실패 처리도 새 시도의 행에 쓰지 않는다.
    row = SentenceAnalysis.objects.get()
    assert (row.status, row.processing_started_at, row.processing_translation_ko) == (
        "processing",
        started[0],
        "새 시도 번역",
    )
    assert row.word_spans is None
    # 옛 시도의 소식은 옛 시도로 보낸다. 새 시도를 기다리는 요청은 받지 않는다.
    assert {message["attempt"] for message in published} <= {
        worker._attempt(old.processing_started_at)
    }


def test_expired_but_unclaimed_late_job_is_saved(client, fake_llm, published):
    analyze(client, TEXT)
    old = left_processing(stream.CLAIM_EXPIRY_SECONDS + 1)
    usage = UsageLog.objects.filter(kind="request").latest("id")

    worker.run_analysis(old.pk, TEXT, usage.pk, old.processing_started_at)

    row = SentenceAnalysis.objects.get()
    assert row.status == SentenceAnalysis.Status.COMPLETE
    assert published[-1]["type"] == "done"
