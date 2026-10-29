"""회원 탈퇴. 화면 탈퇴와 관리자 삭제(이메일 요청, #249)가 같은 결과를 내도록 한곳에 둔다."""

from django.db import transaction

from accounts import tokens
from analysis import usage


def withdraw(user):
    """계정과 개인 기록(원문 기록, 지정한 이름, 확장 토큰, 사용량 기록)을 지운다.

    공용 분석은 남긴다. 사용량 기록은 사용자를 지우면 연결만 비워지므로 먼저 직접 지운다.
    """
    with transaction.atomic():
        # 사용자 행을 잠가, 진행 중인 분석이 지운 사용자의 기록을 새로 남기지 못하게 한다.
        tokens.lock_user(user.pk)
        usage.forget(user)
        user.delete()
