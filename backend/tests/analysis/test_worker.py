"""분석 LLM 작업을 큐·작업자로 옮기기(#98).

대부분의 분석 테스트는 작업을 큐에 넣는 자리에서 바로 실행한다(ANALYSIS_INLINE). 여기서는
선점·구독·작업자 쪽을 따로 본다. 실제 작업자를 띄우는 테스트는 다른 스레드의 요청이 같은 데이터를
봐야 해서 트랜잭션 테스트로 한다.
"""

import threading
import time
from itertools import chain

import pytest
from django.db import connections
from django.db.models import F

from analysis import jobs, views
from analysis.models import SentenceAnalysis, UsageLog
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import Analyzed, analyze, connected_client, post

TEXT = "私は学生です。"


@pytest.fixture
def redis_db():
    """작업 큐와 소식을 비운 Redis."""
    connection = jobs._connection()
    connection.flushdb()
    yield connection
    connection.flushdb()
    connection.close()


def _requests():
    return UsageLog.objects.filter(kind=UsageLog.Kind.REQUEST)


@pytest.mark.django_db
def test_translation_is_saved_and_published_before_the_full_result(client, fake_llm, monkeypatch):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    published = []
    original = jobs.publish

    def recording(sentence_hash, message):
        row = SentenceAnalysis.objects.get(sentence_hash=sentence_hash)
        published.append((message["type"], fake_llm.result_given, row.pending_translation_ko))
        original(sentence_hash, message)

    monkeypatch.setattr(jobs, "publish", recording)

    response = analyze(client, TEXT)

    # 작업자는 응답 전체를 받기 전에 번역을 먼저 저장하고 알린다. 저장을 마치면 비운다.
    assert published == [
        ("translation", False, "나는 학생입니다."),
        ("done", True, None),
    ]
    assert response.types() == ["translation", "analysis"]


@pytest.mark.django_db
def test_failed_llm_leaves_a_failed_row_and_an_error_event(client, fake_llm):
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze(client, TEXT)

    assert response.events == [{"type": "error", "error": "ANALYSIS:FAILED"}]
    row = SentenceAnalysis.objects.get()
    assert (row.status, row.word_spans, row.translation_ko) == ("failed", None, None)


@pytest.mark.django_db
def test_failed_first_try_and_successful_retry_record_usage_on_the_same_analysis(client, fake_llm):
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")
    analyze(client, TEXT)
    fake_llm.error = None
    fake_llm.response = {"translation_ko": "나는 학생입니다."}

    response = analyze(client, TEXT)

    assert response.types() == ["translation", "analysis"]
    row = SentenceAnalysis.objects.get()
    assert row.status == "complete"
    calls = UsageLog.objects.filter(kind=UsageLog.Kind.LLM)
    assert [(c.success, c.analysis_id) for c in calls.order_by("id")] == [
        (False, row.pk),
        (True, row.pk),
    ]
    assert [(r.success, r.analysis_id) for r in _requests().order_by("id")] == [
        (False, row.pk),
        (True, row.pk),
    ]


@pytest.mark.django_db
def test_result_of_an_outdated_job_is_not_saved(client, fake_llm):
    # 작업하는 사이 영향 범위가 바뀌어 세대 번호가 올랐다(반려 등).
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    fake_llm.before_respond = lambda: SentenceAnalysis.objects.update(
        generation=F("generation") + 1
    )

    response = analyze(client, TEXT)

    assert response.types() == ["translation", "error"]
    row = SentenceAnalysis.objects.get()
    assert (row.status, row.word_spans, row.translation_ko) == ("failed", None, None)
    assert not row.span_matches.exists()


@pytest.mark.django_db
def test_each_claim_raises_the_generation(client, fake_llm):
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")
    analyze(client, TEXT)
    assert SentenceAnalysis.objects.get().generation == 0

    analyze(client, TEXT)

    assert SentenceAnalysis.objects.get().generation == 1


@pytest.mark.django_db
def test_late_request_sends_the_saved_translation_and_waits_for_the_running_job(
    client, fake_llm, monkeypatch
):
    analyze(client, TEXT)
    SentenceAnalysis.objects.update(
        status="processing", word_spans=None, pending_translation_ko="처리 중 번역"
    )
    monkeypatch.setattr(views, "WAIT_SECONDS", 0.2)
    fake_llm.forget_requests()

    response = analyze(client, TEXT)

    # 처리 중인 작업에 붙어 LLM을 부르지 않는다. 소식이 오지 않으면 대기 상한에서 닫는다.
    assert fake_llm.requests == []
    translation, error = response.events
    assert (translation["type"], translation["translation_ko"]) == ("translation", "처리 중 번역")
    assert error == {"type": "error", "error": "ANALYSIS:FAILED"}


def _read_in_thread(response, results):
    """다른 스레드에서 스트림을 끝까지 읽는다. 그 스레드의 DB 연결은 끝나면 닫는다."""

    def read():
        try:
            results.append(Analyzed(response))
        finally:
            connections.close_all()

    thread = threading.Thread(target=read)
    thread.start()
    return thread


def _wait_until(condition):
    deadline = time.monotonic() + 10
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.05)


def _work_burst():
    jobs.AnalysisWorker([jobs.QUEUE_NAME], connection=jobs._connection()).work(burst=True)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_same_sentence_at_once_runs_the_llm_once_and_both_requests_get_the_result(
    settings, fake_llm, redis_db
):
    settings.ANALYSIS_INLINE = False
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    results = []

    first = _read_in_thread(post(connected_client(), TEXT), results)
    _wait_until(lambda: _requests().count() == 1)
    second = _read_in_thread(post(connected_client(), TEXT), results)
    _wait_until(lambda: _requests().count() == 2)
    _work_burst()
    first.join(10)
    second.join(10)

    assert len(fake_llm.requests) == 1
    assert [r.types() for r in results] == [["translation", "analysis"]] * 2
    assert {r.json()["translation_ko"] for r in results} == {"나는 학생입니다."}
    assert list(_requests().values_list("success", flat=True)) == [True, True]


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("error", [None, BusinessError(AnalysisError.FAILED, "LLM 호출 실패")])
def test_queue_input_is_gone_after_the_job(settings, fake_llm, redis_db, error):
    settings.ANALYSIS_INLINE = False
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    fake_llm.error = error
    results = []

    reader = _read_in_thread(post(connected_client(), TEXT), results)
    _wait_until(lambda: _requests().count() == 1)
    _work_burst()
    reader.join(10)

    assert results[0].types()[-1] == ("error" if error else "analysis")
    # 성공·실패와 관계없이 원문(분석 텍스트)이 Redis 어디에도 남지 않는다(NFR-12).
    assert all("学生".encode() not in value for value in _stored_values(redis_db))
    assert not redis_db.keys("rq:job:*")


def _stored_values(redis_db):
    for key in redis_db.keys("*"):
        kind = redis_db.type(key)
        if kind == b"hash":
            yield from chain.from_iterable(redis_db.hgetall(key).items())
        elif kind == b"zset":
            yield from redis_db.zrange(key, 0, -1)
        elif kind == b"list":
            yield from redis_db.lrange(key, 0, -1)
        elif kind == b"set":
            yield from redis_db.smembers(key)
        elif kind == b"string":
            yield redis_db.get(key)
