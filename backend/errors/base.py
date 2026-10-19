from dataclasses import dataclass
from types import SimpleNamespace


@dataclass(frozen=True)
class ErrorCode:
    """API 오류 코드. code("도메인:이름")와 status는 클라이언트(web, extension)와의 약속이다."""

    code: str
    status: int


class BusinessError(Exception):
    """API가 정해진 오류 코드로 응답하는 실패. 응답은 errors.handler가 만든다.

    reason은 로그에만 남기는 고정 문구다. 응답에는 나가지 않고, 사용자 원문을 담지 않는다.
    """

    def __init__(self, error_code, reason=""):
        super().__init__(reason or error_code.code)
        self.error_code = error_code


def error_domain(prefix, definitions):
    """도메인의 오류 코드를 만든다. {"FAILED": 502} → .FAILED == ErrorCode("PREFIX:FAILED", 502).

    접두어로 도메인마다 같은 이름(NOT_FOUND 등)을 써도 코드가 겹치지 않는다.
    """
    return SimpleNamespace(
        **{name: ErrorCode(f"{prefix}:{name}", status) for name, status in definitions.items()}
    )
