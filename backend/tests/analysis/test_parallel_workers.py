"""여러 작업자의 병렬 분석과 실패 격리(#218).

운영처럼 작업자마다 프로세스를 따로 띄운다(worker_process). 분석 API·PostgreSQL·Redis·RQ는 그대로
쓰고 LLM만 가짜다. 가짜 LLM은 테스트가 Redis로 보내는 신호를 받아야 응답하므로, 작업이 언제
LLM 단계에 있는지를 sleep 없이 정한다.
"""

import json
import subprocess
import sys
import threading
import time
from datetime import timedelta

import pytest
from django.conf import settings as django_settings
from django.db import connection, connections

from analysis import jobs, stream
from analysis.models import SentenceAnalysis
from analysis.normalize import analysis_text
from analysis.sentence import Sentence
from errors import AnalysisError
from tests.analysis.helpers import Analyzed, connected_client, post
from tests.analysis.test_worker import _requests, _stored_values
from tests.analysis.worker_process import ENTERED, release_key, translation

SENTENCES = ["雨が降る。", "猫が寝ている。", "本を読みました。", "駅まで歩く。", "空が青い。"]

# 작업자 프로세스는 Django와 형태소 사전을 읽고 시작해 기본 상한(10초)보다 오래 걸릴 수 있다.
pytestmark = [
    pytest.mark.timeout(90),
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]


@pytest.fixture
def queued(settings, redis_db, monkeypatch):
    settings.ANALYSIS_INLINE = False
    # 요청이 작업자 프로세스가 뜨기를 기다리는 동안 대기 상한에 걸리지 않게 한다.
    monkeypatch.setattr(stream, "WAIT_SECONDS", 60)
    return redis_db


def _wait_until(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.05)


class Requests:
    """다른 스레드에서 보낸 분석 요청들. 요청마다 선점·합류해 사용 기록이 생긴 뒤 다음을 보낸다."""

    def __init__(self):
        self.results, self.threads = {}, []

    def send(self, key, text):
        def read(response):
            try:
                self.results[key] = Analyzed(response)
            finally:
                connections.close_all()

        count = _requests().count()
        thread = threading.Thread(target=read, args=(post(connected_client(), text),))
        thread.start()
        self.threads.append(thread)
        _wait_until(lambda: _requests().count() == count + 1)

    def wait(self):
        for thread in self.threads:
            thread.join(30)
        return self.results


def sentence(text):
    """분석 API가 그 원문으로 만드는 문장(정규화한 분석 텍스트)"""
    return Sentence(analysis_text(text)[0])


def start_worker(texts):
    """작업자 프로세스 하나를 띄운다. texts는 가짜 LLM이 알아볼 문장들이다."""
    answers = {sentence(text).key_text: index for index, text in enumerate(texts)}
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.analysis.worker_process",
            connection.settings_dict["NAME"],
            django_settings.REDIS_URL,
            json.dumps(answers),
        ],
        cwd=django_settings.BASE_DIR,
        stderr=subprocess.PIPE,
        text=True,
    )


def finish(*workers):
    """작업자가 큐를 비우고 스스로 끝나기를 기다린다. 작업자들이 남긴 analysis_job 기록을 준다."""
    records = []
    for worker in workers:
        _, err = worker.communicate(timeout=60)
        assert worker.returncode == 0, err
        records += [json.loads(line) for line in err.splitlines() if line.startswith('{"event"')]
    return [r for r in records if r["event"] == "analysis_job"]


def entered(redis_db):
    """LLM 단계에 들어온 호출들. (문장 번호, 호출 차수, 작업자 PID)다."""
    return [tuple(map(int, e.split(b":"))) for e in redis_db.lrange(ENTERED, 0, -1)]


def release(redis_db, index, call=1, value="go"):
    redis_db.rpush(release_key(index, call), value)


def saved_translation(text):
    return SentenceAnalysis.objects.get(sentence_hash=sentence(text).sentence_hash).translation_ko


def test_three_workers_take_different_sentences_at_once(queued):
    requests = Requests()
    for index, text in enumerate(SENTENCES):
        requests.send(index, text)
    # 같은 문장의 동시 요청은 작업자가 여럿이어도 앞 요청의 작업에 붙는다.
    requests.send("same", SENTENCES[0])
    workers = [start_worker(SENTENCES) for _ in range(3)]

    # 아무 작업도 놓아 주지 않았는데 세 작업이 저마다 다른 작업자에서 LLM 단계에 있다.
    _wait_until(lambda: len(entered(queued)) == 3, seconds=60)
    assert len({pid for *_, pid in entered(queued)}) == 3
    assert not SentenceAnalysis.objects.filter(status="complete").exists()
    for index in range(len(SENTENCES)):
        release(queued, index)
    jobs_done = finish(*workers)
    results = requests.wait()

    # 문장마다 LLM을 한 번 불렀고, 각 요청은 자기 문장의 결과를 받았다.
    assert sorted(index for index, *_ in entered(queued)) == list(range(len(SENTENCES)))
    for index, text in enumerate(SENTENCES):
        result = results[index]
        assert (result.types()[0], result.types()[-1]) == ("translation", "analysis")
        assert result.json()["translation_ko"] == translation(index, 1)
        assert saved_translation(text) == translation(index, 1)
    assert results["same"].json()["translation_ko"] == translation(0, 1)
    assert sorted(j["result"] for j in jobs_done) == ["done"] * len(SENTENCES)
    # 끝난 작업의 큐 입력(원문)이 Redis에 남지 않는다(NFR-12).
    assert not queued.keys("rq:job:*")
    assert all(text.encode() not in v for v in _stored_values(queued) for text in SENTENCES)


def test_worker_that_timed_out_a_job_goes_on_to_the_next_one(queued, monkeypatch):
    # 실제 120초를 기다리지 않게 이 테스트의 작업만 짧게 끊는다.
    monkeypatch.setattr(jobs, "JOB_TIMEOUT_SECONDS", 2)
    requests = Requests()
    requests.send("stuck", SENTENCES[0])
    requests.send("next", SENTENCES[1])
    # 첫 작업에는 응답 신호를 보내지 않는다. 다음 작업은 들어오자마자 응답한다.
    release(queued, 1)
    worker = start_worker(SENTENCES)

    jobs_done = finish(worker)
    results = requests.wait()

    # 같은 작업자 프로세스가 시간 초과한 작업을 실패로 정리하고 다음 작업을 끝냈다.
    assert [pid for *_, pid in entered(queued)] == [worker.pid, worker.pid]
    assert results["stuck"].events[-1] == {"type": "error", "error": AnalysisError.FAILED.code}
    stuck = SentenceAnalysis.objects.get(sentence_hash=sentence(SENTENCES[0]).sentence_hash)
    assert (stuck.status, stuck.word_spans) == ("failed", None)
    assert results["next"].json()["translation_ko"] == translation(1, 1)
    assert sorted(j["result"] for j in jobs_done) == ["done", "failed"]
    assert not queued.keys("rq:job:*")


def test_outdated_attempt_finishing_late_does_not_overwrite_the_new_result(queued):
    text = SENTENCES[0]
    requests = Requests()
    requests.send("old", text)
    old_worker = start_worker(SENTENCES)
    _wait_until(lambda: len(entered(queued)) == 1, seconds=60)
    # 옛 시도의 작업자가 LLM을 기다리는 사이 선점이 만료되어 다음 요청이 다시 선점한다.
    expired = timedelta(seconds=stream.CLAIM_EXPIRY_SECONDS + 1)
    SentenceAnalysis.objects.update(
        processing_started_at=SentenceAnalysis.objects.get().processing_started_at - expired
    )
    requests.send("new", text)
    new_worker = start_worker(SENTENCES)
    _wait_until(lambda: len(entered(queued)) == 2, seconds=60)

    # 새 시도가 먼저 끝나고, 옛 시도는 그 뒤에 응답을 받는다.
    release(queued, 0, call=2)
    _wait_until(lambda: SentenceAnalysis.objects.get().status == "complete")
    release(queued, 0, call=1)
    jobs_done = finish(old_worker, new_worker)
    results = requests.wait()

    assert saved_translation(text) == translation(0, 2)
    assert results["new"].json()["translation_ko"] == translation(0, 2)
    assert results["old"].events[-1]["type"] == "error"
    assert sorted(j["result"] for j in jobs_done) == ["done", "failed"]
    assert not queued.keys("rq:job:*")


@pytest.mark.parametrize("worker_count", [1, 3])
def test_mock_comparison_of_one_and_three_workers(queued, worker_count):
    """작업자 1개와 3개의 모의 비교(#218). 가짜 LLM이 호출마다 0.3초 생성 시간을 흉내 낸다.

    모든 작업자가 LLM 단계에 들어온 뒤 한꺼번에 놓아 주고, 그때부터 모든 응답이 끝날 때까지를
    잰다. -s로 실행하면 요약을 출력한다. 실제 모델의 속도가 아니다.
    """
    requests = Requests()
    for index, text in enumerate(SENTENCES):
        requests.send(index, text)
    workers = [start_worker(SENTENCES) for _ in range(worker_count)]
    _wait_until(lambda: len(entered(queued)) == worker_count, seconds=60)

    started = time.monotonic()
    for index in range(len(SENTENCES)):
        release(queued, index, value="hold:0.3")
    jobs_done = finish(*workers)
    results = requests.wait()
    elapsed = time.monotonic() - started

    assert all(results[i].types()[-1] == "analysis" for i in range(len(SENTENCES)))
    assert len({j["worker"] for j in jobs_done}) == worker_count
    first = sorted(j["first_response_s"] for j in jobs_done)
    print(
        f"\n[모의 비교] 작업자 {worker_count}개, 미캐시 문장 {len(SENTENCES)}개"
        f"(글자 수 {[len(t) for t in SENTENCES]}), 1회, 성공 {len(jobs_done)}"
        f", 놓아 준 뒤 모두 끝날 때까지 {elapsed:.2f}초"
        f", 작업별 첫 응답 완료 {first}초"
    )
