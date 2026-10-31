"""분석 시간 기록(#216). 큐 대기·LLM 처리·완료 시간을 나눠 보도록 한 줄에 JSON 하나를 남긴다.

기존 식별자(분석 행 ID, 시도, 사용 기록 ID), 시간, 토큰 수, 오류 코드만 싣는다. 원문·프롬프트·
모델 응답·인증 비밀은 싣지 않는다. 한 프로세스 안의 소요 시간은 단조 시계(clock)로 재고, 프로세스
사이의 큐 대기는 DB에 남은 선점 시각과 작업 시작 시각으로 잰다. 칸의 뜻은 docs/analysis-timing.md.
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

# 소요 시간을 재는 단조 시계. 테스트가 바꿔 끼운다.
clock = time.perf_counter


def log(event, **fields):
    logger.info(json.dumps({"event": event, **fields}))


def seconds_since(start):
    return round(clock() - start, 3)


class Record:
    """기록 한 줄. 만든 때(start)부터 잰 단계 시각을 모아 log로 한 번 남긴다.

    fields에 None으로 둔 단계는 mark로 처음 이른 때를 채운다. 이르지 못한 단계는 null로 남는다.
    """

    def __init__(self, event, start=None, **fields):
        self.event = event
        self.start = clock() if start is None else start
        self.fields = fields

    def mark(self, stage):
        key = f"{stage}_s"
        if self.fields[key] is None:
            self.fields[key] = seconds_since(self.start)

    def end(self, result, error=None):
        self.fields.update(result=result, error=error)

    def log(self):
        log(self.event, **self.fields, total_s=seconds_since(self.start))
