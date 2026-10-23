import pytest
from django.contrib.auth import get_user_model

from tests.analysis.helpers import connected_client


@pytest.fixture
def client(db):
    """분석 API는 확장 토큰으로 로그인해야 쓴다(#109). 확장처럼 Bearer 토큰을 붙인다."""
    return connected_client()


@pytest.fixture
def analyst(client):
    """client가 쓰는 토큰의 주인"""
    return get_user_model().objects.get(username="analyst")
