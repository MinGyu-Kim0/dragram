"""내 일본어 항목(#322)의 조회·추가·숨김·해제와 예문 삭제 API. 본인 것만 다룬다.

확장은 Bearer 토큰, 웹은 세션으로 부른다. 세션으로 상태를 바꾸는 요청은 CSRF를 검사한다. 예문
원문은 본문으로만 받고 로그·오류 사유·공용 테이블에 남기지 않는다.
"""

import hashlib

from django.db import transaction
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.tokens import ExtensionTokenAuthentication, lock_user
from accounts.views import SessionUser, require_csrf
from analysis.answers import _is_text
from analysis.models import GrammarUsage, MyExample, MyItem, ReviewStatus, WordSense
from analysis.presenter import _review_status
from analysis.views import MAX_TEXT_LENGTH
from errors.auth import AuthError
from errors.base import BusinessError
from errors.my_items import MyItemError

# 사용자 한 명이 둘 수 있는 항목 수와 항목 하나의 예문 수. 계정 하나가 DB를 끝없이 채우지 못하게
# 한다(지정한 이름의 MAX_NAMES와 같은 이유).
MAX_ITEMS = 10000
MAX_EXAMPLES = 20

_KINDS = {"usage": GrammarUsage, "sense": WordSense}


class TokenOrSession(BaseAuthentication):
    """Authorization 헤더가 있으면 확장 토큰, 없으면 웹 세션이다."""

    def authenticate(self, request):
        if request.META.get("HTTP_AUTHORIZATION"):
            return ExtensionTokenAuthentication().authenticate(request)
        return SessionUser().authenticate(request)


def _invalid(reason):
    return BusinessError(MyItemError.INVALID, reason)


def _target(data):
    """본문의 (종류, 용법·뜻). 없으면 거부한다."""
    if not isinstance(data, dict):
        raise _invalid("본문이 객체가 아님")
    kind, target_id = data.get("kind"), data.get("id")
    if kind not in _KINDS or type(target_id) is not int:
        raise _invalid("종류나 ID가 맞지 않음")
    target = _KINDS[kind].objects.filter(pk=target_id).first()
    if target is None:
        raise _invalid("없는 항목")
    return kind, target


def _rejected(kind, target):
    """화면에 보이지 않는(반려된) 용법·뜻인가. 용법은 패턴까지 본다(ADR 0003)."""
    if kind == "usage":
        return _review_status(target.pattern, target) is None
    return target.sense_status == ReviewStatus.REJECTED


def _example(data):
    """본문의 예문. 없으면 None이다."""
    text = data.get("example")
    if text is None:
        return None
    if not _is_text(text) or len(text) > MAX_TEXT_LENGTH or "\x00" in text:
        raise _invalid("예문이 맞지 않음")
    return text


def _item(row):
    kind = "usage" if row.usage_id else "sense"
    return {"kind": kind, "id": row.usage_id or row.sense_id, "state": row.state}


def _authorized(request):
    if not request.user.is_authenticated:
        raise BusinessError(AuthError.LOGIN_REQUIRED, "로그인하지 않음")
    # 세션으로 상태를 바꾸는 요청만 CSRF를 본다. 토큰 요청은 auth에 토큰 행이 있다.
    if request.method != "GET" and request.auth is None:
        require_csrf(request)


@api_view(["GET", "PUT", "DELETE"])
@authentication_classes([TokenOrSession])
@permission_classes([])
def my_items(request):
    """GET은 내 항목 상태 목록(만든 순), PUT은 추가·숨김(같은 항목이면 상태만 바뀐다. 추가할 때
    example을 주면 예문으로 저장한다), DELETE는 해제(예문도 지운다)다.
    """
    _authorized(request)
    user = request.user
    if request.method == "GET":
        rows = MyItem.objects.filter(user=user).order_by("id")
        return Response({"items": [_item(row) for row in rows]})
    kind, target = _target(request.data)
    if request.method == "DELETE":
        # 반려된 항목도 지울 수 있어야 그 예문(본인 원문)을 언제든 지운다.
        MyItem.objects.filter(user=user, **{kind: target}).delete()
        return Response(status=204)
    if _rejected(kind, target):
        raise _invalid("반려된 항목")
    state, example = request.data.get("state"), _example(request.data)
    if state not in MyItem.State.values or (example is not None and state != MyItem.State.ADDED):
        raise _invalid("상태가 맞지 않거나 숨기며 예문을 줌")
    with transaction.atomic():
        # 같은 사용자의 변경을 직렬화해, 동시에 보내도 상한을 넘지 않게 센다.
        lock_user(user.pk)
        mine = MyItem.objects.filter(user=user)
        if not mine.filter(**{kind: target}).exists() and mine.count() >= MAX_ITEMS:
            raise BusinessError(MyItemError.TOO_MANY, "항목 수 상한")
        row, _ = MyItem.objects.update_or_create(
            user=user, **{kind: target}, defaults={"state": state}
        )
        if example is not None:
            digest = hashlib.sha256(example.encode()).hexdigest()
            if not row.examples.filter(original_hash=digest).exists():
                if row.examples.count() >= MAX_EXAMPLES:
                    raise BusinessError(MyItemError.TOO_MANY, "예문 수 상한")
                MyExample.objects.create(item=row, original_hash=digest, original_text=example)
    return Response(_item(row))


@api_view(["DELETE"])
@authentication_classes([TokenOrSession])
@permission_classes([])
def my_example(request, example_id):
    """내 예문 하나를 지운다."""
    _authorized(request)
    deleted, _ = MyExample.objects.filter(item__user=request.user, pk=example_id).delete()
    if not deleted:
        raise BusinessError(MyItemError.NOT_FOUND, "내 예문에 없음")
    return Response(status=204)
