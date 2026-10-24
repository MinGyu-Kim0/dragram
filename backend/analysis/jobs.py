"""분석 LLM 작업 큐(RQ)와 작업자 소식(Redis pub/sub)(#98, ADR 0005).

큐에 넣는 코드는 enqueue_analysis 하나로 모은다. 나중에 django.tasks로 옮기기 쉽게 하기 위해서다.
큐 입력(분석 텍스트)은 원문이라 작업이 끝나면 성공·실패와 관계없이 바로 지우고(NFR-12), 작업
설명(로그에 찍힌다)에도 넣지 않는다. 소식에는 원문을 넣지 않는다.
"""

import asyncio
import contextlib
import json

import redis
import redis.asyncio
from django.conf import settings
from django.db import close_old_connections
from rq import Queue, SimpleWorker

from errors import AnalysisError, BusinessError

QUEUE_NAME = "analysis"
# 작업 하나의 시간 제한. LLM 요청 전체 마감(llm.REQUEST_DEADLINE_SECONDS, 110초)에 저장할 시간을
# 더한 값이다. 넘으면 RQ가 작업을 멈추고, 작업은 실패로 끝난다.
JOB_TIMEOUT_SECONDS = 120


def _connection():
    return redis.Redis.from_url(settings.REDIS_URL)


def channel(sentence_hash):
    """그 문장의 작업 소식을 보내는 채널. 키 텍스트 해시라 원문이 아니다."""
    return f"analysis:{sentence_hash}"


def enqueue_analysis(analysis_id, text, usage_id):
    """분석 작업을 큐에 넣는다. text는 분석 텍스트, usage_id는 선점한 요청의 request 기록이다.

    Redis에 넣지 못하면 BusinessError다.
    """
    from analysis.worker import run_analysis

    if settings.ANALYSIS_INLINE:
        run_analysis(analysis_id, text, usage_id)
        return
    try:
        Queue(QUEUE_NAME, connection=_connection()).enqueue(
            run_analysis,
            analysis_id,
            text,
            usage_id,
            description=f"analysis {analysis_id}",
            job_timeout=JOB_TIMEOUT_SECONDS,
            result_ttl=0,
            failure_ttl=0,
        )
    except redis.RedisError as e:
        raise BusinessError(AnalysisError.FAILED, "분석 작업을 큐에 넣지 못함") from e


def publish(sentence_hash, message):
    """작업 소식 하나를 보낸다.

    message는 {"type": "translation" | "words" | "done" | "failed", ...}이다.
    """
    with _connection() as connection:
        connection.publish(channel(sentence_hash), json.dumps(message, ensure_ascii=False))


@contextlib.asynccontextmanager
async def listen(sentence_hash):
    """그 문장의 작업 소식을 받는 구독. 블록을 나가면 닫는다."""
    connection = redis.asyncio.Redis.from_url(settings.REDIS_URL)
    try:
        async with connection.pubsub() as pubsub:
            await pubsub.subscribe(channel(sentence_hash))
            yield pubsub
    finally:
        await connection.aclose()


async def messages(pubsub, seconds):
    """구독으로 온 소식을 하나씩 낸다. seconds가 지나면 끝난다."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while (left := deadline - loop.time()) > 0:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=left)
        if message is not None:
            yield json.loads(message["data"])


class AnalysisWorker(SimpleWorker):
    """작업마다 DB 연결을 확인한다. 포크하지 않으므로 SudachiPy 사전을 한 번만 읽는다."""

    def perform_job(self, job, queue):
        close_old_connections()
        try:
            return super().perform_job(job, queue)
        finally:
            close_old_connections()


def work():
    AnalysisWorker([QUEUE_NAME], connection=_connection()).work()
