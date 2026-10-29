import pytest
from django.contrib.auth import get_user_model

from analysis import jobs
from tests.analysis.helpers import connected_client


@pytest.fixture
def client(db):
    """분석 API는 확장 토큰으로 로그인해야 쓴다(#109). 확장처럼 Bearer 토큰을 붙인다."""
    return connected_client()


@pytest.fixture
def analyst(client):
    """client가 쓰는 토큰의 주인"""
    return get_user_model().objects.get(username="analyst")


@pytest.fixture
def redis_db():
    """작업 큐와 소식을 비운 Redis."""
    connection = jobs._connection()
    connection.flushdb()
    yield connection
    connection.flushdb()
    connection.close()


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
