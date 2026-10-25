"""재매칭 재판정을 큐·작업자로 옮기기(#114).

재판정은 문장 해시와 패턴 세트 버전의 Redis 잠금을 잡은 요청만 큐에 넣고, 다른 요청은 그 작업의
소식을 기다린다. 대부분은 작업을 큐에 넣는 자리에서 바로 실행하고(ANALYSIS_INLINE), 동시 조회는
실제 작업자로 본다.
"""

import pytest
import redis
from django.db.models import F

from analysis import jobs, llm, rematch
from analysis.models import SentenceAnalysis, UsageLog
from analysis.sentence import Sentence
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, connected_client, post, span_answer
from tests.analysis.test_rematch import KITEIRU, cache_then_register_teiru, version
from tests.analysis.test_worker import (
    _read_in_thread,
    _stored_values,
    _wait_until,
    _work_burst,
)

pytestmark = pytest.mark.django_db


def lock_key():
    return jobs.rematch_lock_key(Sentence(KITEIRU).sentence_hash, version())


def cached():
    return SentenceAnalysis.objects.get(translation_ko="그가 와 있다")


@pytest.fixture
def holder_calls(monkeypatch):
    """잠금을 못 잡아 잡은 시도를 읽은 횟수(다른 요청의 재판정을 기다리기 시작함)."""
    calls = []
    original = jobs.lock_holder

    def recording(key):
        calls.append(key)
        return original(key)

    monkeypatch.setattr(jobs, "lock_holder", recording)
    return calls


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_same_cached_sentence_at_once_judges_once_and_both_get_the_saved_result(
    settings,
    fake_llm,
    redis_db,
    holder_calls,
):
    cache_then_register_teiru(connected_client(), fake_llm)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    settings.ANALYSIS_INLINE = False
    results = []

    first = _read_in_thread(post(connected_client(), KITEIRU), results)
    _wait_until(lambda: redis_db.exists(lock_key()))
    second = _read_in_thread(post(connected_client(), KITEIRU), results)
    _wait_until(lambda: holder_calls)
    assert 0 < redis_db.ttl(lock_key()) <= jobs.REMATCH_LOCK_SECONDS
    _work_burst()
    first.join(10)
    second.join(10)

    assert len(fake_llm.rematch_requests) == 1
    assert [r.types() for r in results] == [["grammar", "translation", "analysis"]] * 2
    assert [[item["name"] for item in r.json()["grammar"]] for r in results] == [["진행"]] * 2
    assert not redis_db.exists(lock_key())
    # 큐 입력·잠금·소식 어디에도 원문이 남지 않는다.
    assert all("来".encode() not in value for value in _stored_values(redis_db))


def test_failed_judge_falls_back_releases_the_lock_and_is_retried(client, fake_llm, redis_db):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_error = BusinessError(AnalysisError.FAILED, "LLM 재판정 호출 실패")

    response = analyze(client, KITEIRU)

    assert "error" not in response.json()
    assert response.json()["grammar"] == []
    assert not redis_db.exists(lock_key())
    fake_llm.rematch_error = None
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    assert [item["name"] for item in analyze(client, KITEIRU).json()["grammar"]] == ["진행"]
    assert len(fake_llm.rematch_requests) == 2


def test_lock_of_a_dead_job_is_taken_again_after_it_expires(client, fake_llm, redis_db):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    redis_db.set(lock_key(), "dead", ex=jobs.REMATCH_LOCK_SECONDS)

    # 잠금을 잡은 작업이 죽었다. 기다리다 대기 상한에서 대체 응답을 받는다.
    response = analyze(client, KITEIRU)

    assert "error" not in response.json()
    assert response.json()["grammar"] == []
    assert fake_llm.all_requests() == []
    redis_db.pexpire(lock_key(), 1)
    _wait_until(lambda: not redis_db.exists(lock_key()))

    response = analyze(client, KITEIRU)

    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert len(fake_llm.rematch_requests) == 1


def test_late_job_not_holding_the_lock_does_not_call_the_llm(
    client, fake_llm, redis_db, monkeypatch
):
    cache_then_register_teiru(client, fake_llm)
    redis_db.set(lock_key(), "newer", ex=jobs.REMATCH_LOCK_SECONDS)
    usage = UsageLog.objects.filter(kind=UsageLog.Kind.REQUEST).latest("id")
    published = []
    monkeypatch.setattr(jobs, "publish", lambda sentence_hash, message: published.append(message))

    rematch.run_rematch(cached().pk, KITEIRU, usage.id, version(), "older")

    assert fake_llm.all_requests() == []
    assert published == []
    assert redis_db.get(lock_key()) == b"newer"


def test_stale_reanalysis_is_not_blocked_by_the_judge_lock(client, fake_llm, redis_db):
    cache_then_register_teiru(client, fake_llm)
    redis_db.set(lock_key(), "judging", ex=jobs.REMATCH_LOCK_SECONDS)
    SentenceAnalysis.objects.filter(pk=cached().pk).update(
        is_stale=True, generation=F("generation") + 1
    )
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, KITEIRU)

    assert response.types()[-1] == "analysis"
    assert len(fake_llm.requests) == 1
    assert not cached().is_stale


def test_request_code_does_not_make_an_llm_client(
    settings, client, fake_llm, monkeypatch, redis_db
):
    cache_then_register_teiru(client, fake_llm)
    settings.ANALYSIS_INLINE = False
    monkeypatch.setattr(jobs, "enqueue_rematch", lambda *args: None)
    made = []
    monkeypatch.setattr(llm, "get_client", lambda *args: made.append(args))

    response = analyze(client, KITEIRU)

    # 작업자가 없어 소식이 오지 않는다. 대기 상한에서 대체 응답을 받는다.
    assert "error" not in response.json()
    assert made == []


def test_user_over_the_limit_waits_on_a_judge_another_request_took(
    settings, client, fake_llm, redis_db
):
    cache_then_register_teiru(client, fake_llm)
    redis_db.set(lock_key(), "other", ex=jobs.REMATCH_LOCK_SECONDS)
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1

    response = analyze(client, KITEIRU)

    # 다른 요청의 재판정을 기다린다. 소식이 오지 않아 대기 상한에서 대체 응답을 받을 뿐이다.
    assert response.types() == ["grammar", "translation", "analysis"]
    assert fake_llm.all_requests() == []
    assert redis_db.get(lock_key()) == b"other"


def test_job_whose_version_was_raised_while_queued_does_not_call_the_llm(
    client, fake_llm, redis_db, monkeypatch
):
    cache_then_register_teiru(client, fake_llm)
    old_version = version() - 1
    old_key = jobs.rematch_lock_key(Sentence(KITEIRU).sentence_hash, old_version)
    redis_db.set(old_key, "mine", ex=jobs.REMATCH_LOCK_SECONDS)
    usage = UsageLog.objects.filter(kind=UsageLog.Kind.REQUEST).latest("id")
    published = []
    monkeypatch.setattr(jobs, "publish", lambda sentence_hash, message: published.append(message))

    rematch.run_rematch(cached().pk, KITEIRU, usage.id, old_version, "mine")

    # 새 버전의 잠금을 잡을 조회가 재판정한다.
    assert fake_llm.all_requests() == []
    assert published == [{"type": "failed", "attempt": "mine"}]
    assert not redis_db.exists(old_key)


def test_lost_redis_subscription_still_sends_the_saved_analysis(client, fake_llm, monkeypatch):
    cache_then_register_teiru(client, fake_llm)

    def unreachable(sentence_hash):
        raise redis.ConnectionError("Redis에 연결하지 못함")

    monkeypatch.setattr(jobs, "listen", unreachable)

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "analysis"]
    assert response.events[1]["ruby"]
    assert response.json()["translation_ko"] == "그가 와 있다"
    assert fake_llm.all_requests() == []
