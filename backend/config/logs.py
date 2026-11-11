import logging
import sys


def _details(exc, seen):
    """예외와 그 원인·문맥 예외의 메시지에서 PostgreSQL DETAIL(그 줄부터 메시지 끝)을 모은다."""
    if exc is None or id(exc) in seen:
        return []
    seen.add(id(exc))
    try:
        message = str(exc)
    except Exception:  # 메시지를 못 만드는 예외 하나 때문에 로그 전체를 잃지 않는다.
        message = ""
    start = message.find("\nDETAIL:")
    found = [message[start:]] if start != -1 else []
    for linked in (exc.__cause__, exc.__context__, *getattr(exc, "exceptions", ())):
        found += _details(linked, seen)
    return found


class Formatter(logging.Formatter):
    """PostgreSQL 오류의 DETAIL(실패한 행을 통째로 실어 사용자 원문이 들어갈 수 있다)을 지운다.

    출력에서 경계를 추측하지 않고, 예외 객체의 메시지에서 DETAIL 부분을 그대로 찾아 바꾼다.
    """

    def format(self, record):
        text = super().format(record)
        # 예외는 exc_info에도 실리고, RQ 작업 실패처럼 except 블록 안에서 메시지 본문에도 실린다.
        seen = set()
        for exc in (record.exc_info[1] if record.exc_info else None, sys.exc_info()[1]):
            for detail in _details(exc, seen):
                text = text.replace(detail, "\nDETAIL: (생략)")
        return text
