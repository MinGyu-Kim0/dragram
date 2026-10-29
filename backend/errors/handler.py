import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler

from errors.base import BusinessError

logger = logging.getLogger(__name__)


def handle_exception(exc, context):
    """BusinessError는 {"error": code}와 정해진 상태 코드로 응답한다. 나머지는 DRF 기본 처리.

    로그에는 고정 문구와 원인 예외만 남긴다. 원문은 예외에 담지 않으므로 남지 않는다.
    """
    if isinstance(exc, BusinessError):
        log_business_error(exc)
        return Response({"error": exc.error_code.code}, status=exc.error_code.status)
    return exception_handler(exc, context)


def log_business_error(exc):
    """5xx 비즈니스 오류를 남긴다. 스트림 도중의 오류처럼 핸들러를 거치지 않을 때도 쓴다."""
    if exc.error_code.status >= 500:
        logger.warning("%s: %s", exc.error_code.code, exc, exc_info=exc.__cause__ is not None)
