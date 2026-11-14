"""내 일본어 항목(#322)의 조회·추가·제외·숨김·복원·해제와 예문 삭제 API. 본인 것만 다룬다.

추가·제외(added)와 숨김·복원(hidden)은 따로 바꾼다(#362). 스토어에 배포된 옛 확장을 위해 state
칸도 받고 돌려준다: 받은 added는 추가하며 숨김을 풀고, hidden은 숨긴다. 돌려줄 때는 숨겼으면
hidden, 아니면 added다.

확장은 Bearer 토큰, 웹은 세션으로 부른다. 세션으로 상태를 바꾸는 요청은 CSRF를 검사한다. 예문
원문은 본문으로만 받고 로그·오류 사유·공용 테이블에 남기지 않는다.
"""

import hashlib

from django.db import transaction
from django.db.models import Exists, OuterRef
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
    # 목록·객체는 해시할 수 없어 사전 조회가 TypeError가 되므로 문자열인지 먼저 본다.
    if not isinstance(kind, str) or kind not in _KINDS or type(target_id) is not int:
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
    """본문의 예문과 그 안에서 카드가 가리키는 구간(UTF-16 [start, end)). 없으면 None이다."""
    text = data.get("example")
    if text is None:
        if "example_start" in data or "example_end" in data:
            raise _invalid("예문 없이 구간을 줌")
        return None
    if not _is_text(text) or len(text) > MAX_TEXT_LENGTH:
        raise _invalid("예문이 맞지 않음")
    start, end = data.get("example_start"), data.get("example_end")
    length = len(text.encode("utf-16-le")) // 2
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= length:
        raise _invalid("예문 구간이 맞지 않음")
    return text, start, end


def _item(kind, target_id, added, hidden):
    if added or hidden:
        state = "hidden" if hidden else "added"
    else:
        state = None
    return {"kind": kind, "id": target_id, "added": added, "hidden": hidden, "state": state}


def _row_item(row):
    kind = "usage" if row.usage_id else "sense"
    return _item(kind, row.usage_id or row.sense_id, row.added, row.hidden)


def _changes(data):
    """본문이 바꾸는 축 {added?, hidden?}. 옛 확장의 state도 옮긴다. 없거나 맞지 않으면 거부한다."""
    if "state" in data:
        if "added" in data or "hidden" in data:
            raise _invalid("state와 두 축을 함께 줌")
        state = data["state"]
        if state == "added":
            return {"added": True, "hidden": False}
        if state == "hidden":
            return {"hidden": True}
        raise _invalid("상태가 맞지 않음")
    changes = {axis: data[axis] for axis in ("added", "hidden") if axis in data}
    if not changes or any(type(value) is not bool for value in changes.values()):
        raise _invalid("바꿀 축이 없거나 참거짓이 아님")
    return changes


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
    """GET은 내 항목 상태와 예문 유무 목록(만든 순), PUT은 추가·제외·숨김·복원(added·hidden 중
    준 축만 바꾼다. 추가할 때 example과 그 안의 카드 구간 example_start·example_end를 주면
    예문으로 저장한다. 제외하면 예문을 지우고, 두 축이 모두 꺼지면 항목을 지운다), DELETE는
    해제(두 축을 모두 끄고 예문도 지운다)다.
    """
    _authorized(request)
    user = request.user
    if request.method == "GET":
        # 예문이 있는지도 알려, 확장이 제외하기 전에 예문 삭제를 확인받게 한다.
        rows = (
            MyItem.objects.filter(user=user)
            .annotate(has_examples=Exists(MyExample.objects.filter(item=OuterRef("pk"))))
            .order_by("id")
        )
        return Response(
            {"items": [{**_row_item(row), "has_examples": row.has_examples} for row in rows]}
        )
    kind, target = _target(request.data)
    if request.method == "DELETE":
        # 반려된 항목도 지울 수 있어야 그 예문(본인 원문)을 언제든 지운다.
        MyItem.objects.filter(user=user, **{kind: target}).delete()
        return Response(status=204)
    if _rejected(kind, target):
        raise _invalid("반려된 항목")
    changes, example = _changes(request.data), _example(request.data)
    # 예문은 추가하는 요청에만 붙는다(숨기며 함께 주면 거부한다).
    if example is not None and (changes.get("added") is not True or changes.get("hidden")):
        raise _invalid("추가하지 않으며 예문을 줌")
    with transaction.atomic():
        # 같은 사용자의 변경을 직렬화해, 동시에 보내도 상한을 넘지 않게 센다.
        lock_user(user.pk)
        mine = MyItem.objects.filter(user=user)
        # 사용자 잠금을 쓰지 않는 DELETE(옛 확장)가 그사이 지우지 못하게 행도 잠근다(PR #364 리뷰).
        row = mine.filter(**{kind: target}).select_for_update().first()
        added = changes.get("added", row.added if row else False)
        hidden = changes.get("hidden", row.hidden if row else False)
        if not (added or hidden):
            # 제외·복원으로 두 축이 모두 꺼졌다. 예문도 함께 지워진다.
            if row is not None:
                row.delete()
            return Response(_item(kind, target.pk, False, False))
        if row is None:
            if mine.count() >= MAX_ITEMS:
                raise BusinessError(MyItemError.TOO_MANY, "항목 수 상한")
            row = MyItem.objects.create(user=user, **{kind: target}, added=added, hidden=hidden)
        else:
            row.added, row.hidden = added, hidden
            row.save(update_fields=["added", "hidden", "updated_at"])
        if not added:
            # 제외하면 예문을 지운다. 예문은 추가된 항목에만 둔다.
            row.examples.all().delete()
        if example is not None:
            text, start, end = example
            digest = hashlib.sha256(text.encode()).hexdigest()
            if not row.examples.filter(original_hash=digest).exists():
                if row.examples.count() >= MAX_EXAMPLES:
                    raise BusinessError(MyItemError.TOO_MANY, "예문 수 상한")
                MyExample.objects.create(
                    item=row,
                    original_hash=digest,
                    original_text=text,
                    highlight_start=start,
                    highlight_end=end,
                )
    return Response(_row_item(row))


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
