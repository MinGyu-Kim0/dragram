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
        code, status = exc.error_code.code, exc.error_code.status
        if status >= 500:
            logger.warning("%s: %s", code, exc, exc_info=exc.__cause__ is not None)
        return Response({"error": code}, status=status)
    return exception_handler(exc, context)
