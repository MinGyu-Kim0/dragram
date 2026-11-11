import logging
import re

# DETAIL 줄부터 그 예외 메시지 끝(다음 예외로 넘어가는 문구나 기록 끝)까지. 원문에 빈 줄이
# 있어도 이어서 지운다.
_DB_DETAIL = re.compile(
    r"^DETAIL:.*?(?=\n\nThe above exception|\n\nDuring handling of the above|\Z)", re.M | re.S
)


class Formatter(logging.Formatter):
    """PostgreSQL 오류의 DETAIL(실패한 행을 통째로 실어 사용자 원문이 들어갈 수 있다)을 지운다."""

    def format(self, record):
        # 예외 메시지는 traceback(exc_info)에도, RQ 작업 실패처럼 메시지 본문에도 실린다.
        return _DB_DETAIL.sub("DETAIL: (생략)", super().format(record))
