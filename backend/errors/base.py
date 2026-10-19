class BusinessError(Exception):
    """API가 정해진 오류 코드로 응답하는 실패. 처리는 errors.handler가 한다.

    code와 status는 클라이언트(web, extension)와의 약속이라 바꾸면 클라이언트도 바꿔야 한다.
    메시지는 로그에만 남기는 고정 문구이고 사용자 원문을 담지 않는다. 예외 클래스는 도메인
    모듈을 import하지 않는다(순환 import 방지).
    """

    code = "error"
    status = 500
