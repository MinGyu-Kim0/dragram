"""지정한 이름(#136)의 조회·저장·삭제 API. 본인 것만 다룬다.

표기·읽기는 개인 데이터라 로그·오류 사유·사용 기록에 남기지 않는다.
"""

from django.db import transaction
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.tokens import ExtensionTokenAuthentication, lock_user
from analysis.jmdict import to_hiragana
from analysis.models import DesignatedName
from analysis.words import is_kana
from errors.base import BusinessError
from errors.names import DesignatedNameError

MAX_LENGTH = DesignatedName._meta.get_field("surface").max_length
# 사용자 한 명이 지정할 수 있는 표기 수. 계정 하나가 DB를 끝없이 채우지 못하게 한다(PR #167 리뷰).
MAX_NAMES = 1000


def _surface(data):
    surface = data.get("surface") if isinstance(data, dict) else None
    if not isinstance(surface, str) or not surface.strip() or len(surface) > MAX_LENGTH:
        raise BusinessError(DesignatedNameError.INVALID, "표기가 맞지 않음")
    return surface


def _reading(data):
    """히라가나로 바꾼 읽기. 비었으면 None이다."""
    reading = data.get("reading")
    if reading is None or reading == "":
        return None
    if not isinstance(reading, str) or len(reading) > MAX_LENGTH or not is_kana(reading):
        raise BusinessError(DesignatedNameError.INVALID, "읽기가 가나가 아님")
    return to_hiragana(reading)


def _item(name):
    return {"surface": name.surface, "reading": name.reading}


@api_view(["GET", "PUT", "DELETE"])
@authentication_classes([ExtensionTokenAuthentication])
@permission_classes([])
def designated_names(request):
    """GET은 내 지정한 이름 목록, PUT은 지정(같은 표기면 읽기만 갱신), DELETE는 지정 해제다.
    표기는 URL에 넣지 않고 본문으로 받는다. 접근 로그에 남지 않게 하기 위해서다.
    """
    user = request.user
    if request.method == "GET":
        rows = DesignatedName.objects.filter(user=user).order_by("surface")
        return Response({"names": [_item(name) for name in rows]})
    surface = _surface(request.data)
    if request.method == "DELETE":
        DesignatedName.objects.filter(user=user, surface=surface).delete()
        return Response(status=204)
    reading = _reading(request.data)
    with transaction.atomic():
        # 같은 사용자의 지정을 직렬화해, 동시에 보내도 상한을 넘지 않게 센다.
        lock_user(user.pk)
        mine = DesignatedName.objects.filter(user=user)
        if not mine.filter(surface=surface).exists() and mine.count() >= MAX_NAMES:
            raise BusinessError(DesignatedNameError.TOO_MANY, "지정한 이름 수 상한")
        name, _ = DesignatedName.objects.update_or_create(
            user=user, surface=surface, defaults={"reading": reading}
        )
    return Response(_item(name))
