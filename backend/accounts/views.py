"""웹 로그인 세션 API. 웹과 API는 같은 출처에서 Django 세션·CSRF를 쓴다(#92)."""

import uuid

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import Http404
from django.middleware.csrf import CsrfViewMiddleware
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts import google
from accounts.models import User
from errors.auth import AuthError
from errors.base import BusinessError


class SessionUser(BaseAuthentication):
    """Django 세션의 사용자. CSRF는 각 뷰가 require_csrf로 직접 검사한다.

    DRF의 SessionAuthentication은 로그인한 요청만 CSRF를 보고 오류 모양도 달라, 로그인 전
    요청(Google 로그인)과 같은 오류 코드로 거부하려고 따로 둔다.
    """

    def authenticate(self, request):
        user = getattr(request._request, "user", None)
        if user is None or not user.is_active or not user.is_authenticated:
            return None
        return (user, None)


def require_csrf(request):
    """상태를 바꾸는 요청의 CSRF 값(X-CSRFToken 헤더 + 쿠키)을 검사한다."""
    check = CsrfViewMiddleware(lambda r: None)
    check.process_request(request._request)
    if check.process_view(request._request, None, (), {}) is not None:
        raise BusinessError(AuthError.CSRF_FAILED, "CSRF 검사 실패")


def _field(request, name, error_code):
    """JSON 객체 본문의 칸. 본문이 객체가 아니면(배열, 문자열 등) error_code로 거부한다."""
    if not isinstance(request.data, dict):
        raise BusinessError(error_code, "본문이 객체가 아님")
    return request.data.get(name)


def _user_body(user):
    return {"user": {"email": user.email} if user.is_authenticated else None}


def _start_session(request, user):
    if not user.is_active:
        raise BusinessError(AuthError.ACCOUNT_DISABLED, "막힌 계정")
    auth.login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response(_user_body(user))


@api_view(["GET"])
@authentication_classes([SessionUser])
@permission_classes([])
@ensure_csrf_cookie
def me(request):
    """현재 로그인 사용자. 웹이 쓸 CSRF 쿠키도 함께 준다."""
    return Response(_user_body(request.user))


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def google_login(request):
    """Google ID 토큰으로 로그인한다. 처음이면 사용자를 만들고, 이메일은 매번 갱신한다."""
    require_csrf(request)
    account = google.verify(_field(request, "credential", AuthError.GOOGLE_TOKEN_INVALID))
    user, _ = User.objects.update_or_create(
        google_sub=account.sub,
        defaults={"email": account.email},
        create_defaults={
            # sub는 255자까지 될 수 있어 150자 username에 넣지 않는다.
            "username": f"google-{uuid.uuid4().hex}",
            "email": account.email,
            "password": make_password(None),
        },
    )
    return _start_session(request, user)


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def logout(request):
    require_csrf(request)
    auth.logout(request._request)
    return Response(_user_body(request._request.user))


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def dev_login(request):
    """로컬 수동 확인용: 이메일만으로 로그인한다. DEBUG이고 DEV_LOGIN_ENABLED일 때만 연다."""
    # 오류 코드로 답하지 않고 없는 주소처럼 404를 낸다. 꺼져 있을 때 있다는 것조차 알리지 않는다.
    if not (settings.DEBUG and settings.DEV_LOGIN_ENABLED):
        raise Http404
    require_csrf(request)
    email = _field(request, "email", AuthError.DEV_EMAIL_INVALID)
    # username(150자)에 접두어와 함께 넣으므로 길이를 제한한다.
    if not isinstance(email, str) or len(email) > 140:
        raise BusinessError(AuthError.DEV_EMAIL_INVALID, "개발 로그인 이메일 아님")
    try:
        validate_email(email)
    except ValidationError as e:
        raise BusinessError(AuthError.DEV_EMAIL_INVALID, "개발 로그인 이메일 아님") from e
    user, _ = User.objects.get_or_create(
        username=f"dev:{email}", defaults={"email": email, "password": make_password(None)}
    )
    return _start_session(request, user)
