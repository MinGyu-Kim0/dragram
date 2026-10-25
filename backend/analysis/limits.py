"""사용자별 비용 안전장치(#28, NFR-14): 하루 LLM 토큰 한도와 동시 분석 요청 제한. 원문은
다루지 않는다.
"""

import logging
import time
import uuid

import redis
from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from analysis import jobs
from analysis.models import UsageLog
from errors import AnalysisError, BusinessError

logger = logging.getLogger(__name__)

# 서버 프로세스가 죽어 빼지 못한 동시 요청 셈은 이 시간 뒤 빠진다. 요청 최대 대기(130초)보다 길다.
ACTIVE_SECONDS = 150


def today_tokens(user):
    """오늘(Asia/Seoul 자정부터) 그 사용자의 llm 행 입력+출력 토큰 합. NULL은 0이다."""
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    tokens = Coalesce("input_tokens", 0) + Coalesce("output_tokens", 0)
    rows = UsageLog.objects.filter(kind=UsageLog.Kind.LLM, user=user, created_at__gte=midnight)
    return rows.aggregate(total=Coalesce(Sum(tokens), 0))["total"]


def over_limit(user):
    """LLM을 새로 부르면 안 되는가. 이미 큐에 들어간 작업은 막지 않아 한도를 조금 넘을 수 있다."""
    if user is None:
        # 하루 한도는 사용자별이다. 관리 명령(평가 #177)은 사용자 없이 부른다.
        return False
    return today_tokens(user) >= settings.ANALYSIS_DAILY_TOKEN_LIMIT


def _active_key(user):
    return f"analysis:active:{user.pk}"


def enter(user):
    """그 사용자의 동시 분석 요청 셈에 이 요청을 넣고, 셈에서 뺄 함수를 돌려준다.

    여러 서버 프로세스가 함께 세도록 Redis 정렬 집합에 요청마다 들어온 시각으로 넣는다. 넣고 센
    수가 상한을 넘으면 도로 빼고 BusinessError다.
    """
    key, member, now = _active_key(user), uuid.uuid4().hex, time.time()
    try:
        with jobs._connection() as connection:
            pipe = connection.pipeline()
            pipe.zremrangebyscore(key, "-inf", now - ACTIVE_SECONDS)
            pipe.zadd(key, {member: now})
            pipe.expire(key, ACTIVE_SECONDS)
            pipe.zcard(key)
            count = pipe.execute()[-1]
            if count > settings.ANALYSIS_MAX_CONCURRENT:
                connection.zrem(key, member)
    except redis.RedisError as e:
        raise BusinessError(AnalysisError.FAILED, "동시 요청 셈을 하지 못함") from e
    if count > settings.ANALYSIS_MAX_CONCURRENT:
        raise BusinessError(AnalysisError.TOO_MANY_REQUESTS, "동시 분석 요청 상한")

    def leave():
        try:
            with jobs._connection() as connection:
                connection.zrem(key, member)
        except redis.RedisError:
            # 셈은 ACTIVE_SECONDS 뒤 저절로 빠진다.
            logger.warning("동시 요청 셈에서 빼지 못함: user_id=%s", user.pk)

    return leave
