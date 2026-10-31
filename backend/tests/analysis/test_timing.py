"""분석 시간 기록(#216). 운영자가 큐 대기·첫 번역·첫 응답 완료·보조 호출·전체 완료를 나눠 본다.

실제 작업자를 띄우는 테스트는 분석 API·PostgreSQL·Redis·RQ 작업자·NDJSON 응답을 그대로 쓰고 LLM만
바꿔 끼운다. 단계 시각은 가짜 시계로 정해, 기록이 어느 단계를 재는지 확인한다.
"""

import json
import logging

import pytest

from analysis import llm, timing, worker
from analysis.models import SentenceAnalysis
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, connected_client, post
from tests.analysis.test_worker import _read_in_thread, _requests, _wait_until, _work_burst
from tests.conftest import FakeLLMClient

TEXT = "私は学生です。"
TRANSLATION = "나는 학생입니다."


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class SteppedLLM(FakeLLMClient):
    """스트림이 번역·응답 전체를 넘기기 전에 가짜 시계를 정한 만큼 돌린다. fail_after 칸을 넘긴
    뒤에는 스트림이 끊긴다.
    """

    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.steps = {"translation": 2, "result": 5}
        self.fail_after = None

    def analyze_stream(self, *args):
        for kind, value in super().analyze_stream(*args):
            self.clock.now += self.steps.get(kind, 0)
            yield kind, value
            if kind == self.fail_after:
                raise BusinessError(AnalysisError.FAILED, "LLM 스트림 실패")


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(timing, "clock", fake)
    return fake


@pytest.fixture
def stepped(monkeypatch, clock):
    client = SteppedLLM(clock)
    client.response = {"translation_ko": TRANSLATION}
    monkeypatch.setattr(llm, "get_client", client.connect)
    return client


@pytest.fixture
def logs(caplog):
    """기록된 시간 기록을 종류별로 읽는다. 모든 로거의 INFO 이상을 잡아 둔다."""
    caplog.set_level(logging.INFO)

    def of(event):
        records = [r for r in caplog.records if r.name == timing.logger.name]
        return [
            line
            for line in map(json.loads, (r.getMessage() for r in records))
            if line["event"] == event
        ]

    of.text = lambda: caplog.text
    return of


def _analyze_with_worker(*clients):
    """요청들을 다른 스레드에서 보내 모두 작업을 기다리게 한 뒤, 실제 작업자로 큐를 비운다."""
    results, readers = [], []
    for n, client in enumerate(clients, 1):
        readers.append(_read_in_thread(post(client, TEXT), results))
        _wait_until(lambda n=n: _requests().count() == n)
    _work_burst()
    for reader in readers:
        reader.join(10)
    return results


@pytest.fixture
def queued(settings, redis_db):
    settings.ANALYSIS_INLINE = False


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_normal_analysis_separates_queue_wait_translation_first_response_and_completion(
    queued, stepped, logs
):
    client = connected_client()

    [result] = _analyze_with_worker(client)

    assert result.types() == ["translation", "analysis"]
    row = SentenceAnalysis.objects.get()
    request_id = _requests().get().pk
    [job] = logs("analysis_job")
    assert (job["analysis_id"], job["request_id"]) == (row.pk, request_id)
    assert job["attempt"] == worker._attempt(row.processing_started_at)
    assert (job["result"], job["error"]) == ("done", None)
    # 큐 대기는 선점 시각부터 작업 시작까지라 다른 프로세스의 벽시계로 잰다.
    assert job["queue_wait_s"] >= 0
    # 작업 안의 단계는 작업 시작부터 잰다. 보조 호출은 시계를 돌리지 않았다.
    assert (job["translation_s"], job["first_response_s"], job["total_s"]) == (2, 7, 7)
    assert job["worker"]

    calls = logs("llm_call")
    assert calls[0]["purpose"] == "first_response"
    assert {(c["request_id"], c["analysis_id"]) for c in calls} == {(request_id, row.pk)}
    assert (calls[0]["input_tokens"], calls[0]["output_tokens"]) == (100, 10)

    [request] = logs("analysis_request")
    assert (request["role"], request["request_id"]) == ("claimed", request_id)
    assert (request["analysis_id"], request["attempt"]) == (row.pk, job["attempt"])
    assert (request["result"], request["error"]) == ("done", None)
    assert request["translation_s"] <= request["analysis_s"] <= request["total_s"]

    # 원문·번역(모델 응답)·인증 토큰이 어느 로그에도 없다.
    text = logs.text()
    token = client.defaults["HTTP_AUTHORIZATION"].removeprefix("Bearer ")
    for secret in (TEXT, "学生", TRANSLATION, token, llm.INSTRUCTIONS[:40]):
        assert secret not in text


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_failure_after_the_translation_keeps_the_stages_it_reached(queued, stepped, logs):
    stepped.fail_after = "translation"

    [result] = _analyze_with_worker(connected_client())

    assert result.types() == ["translation", "error"]
    [job] = logs("analysis_job")
    assert (job["result"], job["error"]) == ("failed", AnalysisError.FAILED.code)
    # 받지 못한 첫 응답 완료는 비워 둔다.
    assert (job["translation_s"], job["first_response_s"]) == (2, None)
    [request] = logs("analysis_request")
    assert (request["result"], request["error"]) == ("error", AnalysisError.FAILED.code)
    assert request["translation_s"] is not None
    assert request["analysis_s"] is None


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_failure_before_the_first_response_reaches_no_stage_and_no_tokens(queued, stepped, logs):
    stepped.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")
    # 응답을 받지 못해 공급자의 토큰 사용량이 없다.
    stepped.usage = (None, None, None)

    [result] = _analyze_with_worker(connected_client())

    assert result.types() == ["error"]
    [job] = logs("analysis_job")
    assert (job["result"], job["translation_s"], job["first_response_s"]) == ("failed", None, None)
    [call] = logs("llm_call")
    assert (call["success"], call["input_tokens"], call["output_tokens"]) == (False, None, None)
    [request] = logs("analysis_request")
    assert (request["result"], request["translation_s"], request["analysis_s"]) == (
        "error",
        None,
        None,
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_shared_job_is_logged_once_and_each_request_keeps_its_own_wait(queued, stepped, logs):
    results = _analyze_with_worker(connected_client(), connected_client())

    assert [r.types() for r in results] == [["translation", "analysis"]] * 2
    [job] = logs("analysis_job")
    requests = sorted(logs("analysis_request"), key=lambda r: r["request_id"])
    assert [r["role"] for r in requests] == ["claimed", "joined"]
    assert job["request_id"] == requests[0]["request_id"]
    assert {(r["analysis_id"], r["attempt"]) for r in requests} == {
        (job["analysis_id"], job["attempt"])
    }
    assert all(r["result"] == "done" for r in requests)
    # 작업은 한 번만 LLM을 불렀다.
    assert [c["purpose"] for c in logs("llm_call")].count("first_response") == 1


@pytest.mark.django_db
def test_cached_answer_is_not_logged_as_an_llm_run(client, fake_llm, logs):
    analyze(client, TEXT)
    jobs_before, calls_before = len(logs("analysis_job")), len(logs("llm_call"))

    response = analyze(client, TEXT)

    assert response.types() == ["translation", "analysis"]
    assert (len(logs("analysis_job")), len(logs("llm_call"))) == (jobs_before, calls_before)
    assert logs("analysis_request")[-1]["role"] == "cache"


@pytest.mark.django_db
def test_job_that_breaks_with_a_bug_is_still_logged_as_failed(client, fake_llm, logs, monkeypatch):
    def broken_in_worker(text):
        raise RuntimeError("작업자 준비 중 버그")

    monkeypatch.setattr(worker, "Sentence", broken_in_worker)

    with pytest.raises(RuntimeError):
        analyze(client, TEXT)

    [job] = logs("analysis_job")
    assert (job["result"], job["error"]) == ("failed", AnalysisError.FAILED.code)
