"""통합 테스트가 따로 띄우는 작업자 프로세스(#218). 운영처럼 프로세스 하나에 RQ 작업자 하나가 돈다.

LLM만 가짜로 바꾼다. 가짜 LLM은 Redis 목록으로 테스트와 신호를 주고받는다. 첫 분석 호출에 들어오면
ENTERED에 '문장 번호:그 문장의 호출 차수:PID'를 넣는다. 그다음 release_key(문장 번호, 차수)에 값이
올 때까지 기다린다. 값이 'hold:초'면 그만큼 생성 시간을 흉내 내고, 'timeout'이면 LLM 클라이언트의
스트림 시간 초과처럼 실패한다. 원문은 Redis에 넣지 않는다.

    python -m tests.analysis.worker_process <테스트 DB> <Redis URL> <{분석 텍스트: 문장 번호} JSON>
"""

import json
import os
import sys
import time

ENTERED = "test:llm:entered"
# 신호를 기다리는 상한. 테스트가 신호를 보내지 않는 작업은 그 전에 작업 시간 제한에 걸린다.
WAIT_SECONDS = 30


def release_key(index, call):
    return f"test:llm:release:{index}:{call}"


def translation(index, call):
    """가짜 LLM이 그 문장의 그 호출에 내는 번역"""
    return f"번역 {index}-{call}"


def main(db_name, redis_url, answers):
    # 설정을 읽기 전에 테스트 DB를 가리킨다.
    os.environ["POSTGRES_DB"] = db_name
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    import redis
    from django.conf import settings

    from analysis import jobs, llm
    from errors import AnalysisError, BusinessError
    from tests.conftest import FakeLLMClient

    settings.REDIS_URL = redis_url
    signals = redis.Redis.from_url(redis_url)

    class GatedLLM(FakeLLMClient):
        def analyze_stream(self, sentence, *args):
            index = answers[sentence]
            call = signals.incr(f"test:llm:calls:{index}")
            signals.rpush(ENTERED, f"{index}:{call}:{os.getpid()}")
            released = signals.blpop([release_key(index, call)], timeout=WAIT_SECONDS)
            if released and released[1].startswith(b"hold:"):
                time.sleep(float(released[1].removeprefix(b"hold:")))
            if released and released[1] == b"timeout":
                raise BusinessError(AnalysisError.FAILED, "LLM 스트림 전체 시간 초과")
            self.response = {"translation_ko": translation(index, call)}
            yield from super().analyze_stream(sentence, *args)

    client = GatedLLM()
    llm.get_client = client.connect
    jobs.AnalysisWorker([jobs.QUEUE_NAME], connection=jobs._connection()).work(burst=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]))
