"""웹 로그인 세션 API. 웹과 API는 같은 출처에서 Django 세션·CSRF를 쓴다(#92)."""

import uuid

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import Http404
from django.middleware.csrf import CsrfViewMiddleware
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts import google, tokens
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


def _lock_user(user_or_id):
    """같은 사용자의 확장 토큰 발급과 웹 로그아웃·로그인을 직렬화한다(트랜잭션 안에서 부른다)."""
    pk = getattr(user_or_id, "pk", user_or_id)
    User.objects.select_for_update().filter(pk=pk).first()


def _user_body(user):
    return {"user": {"email": user.email} if user.is_authenticated else None}


def _start_session(request, user):
    if not user.is_active:
        raise BusinessError(AuthError.ACCOUNT_DISABLED, "막힌 계정")
    session = request._request.session
    previous_key = session.session_key
    # 세션에 로그인해 있던 사용자. 막힌 계정은 인증되지 않지만 세션에는 남아 있어 함께 본다.
    previous_id = session.get(auth.SESSION_KEY)
    with transaction.atomic():
        if previous_id is not None:
            _lock_user(previous_id)
        # login은 세션 키를 바꾸고, 다른 사용자면 세션을 비운다.
        auth.login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        if previous_key:
            # 이전 세션이 발급한 토큰: 다른 사용자 것은 폐기하고, 같은 사용자 것은 다음 웹
            # 로그아웃이 찾도록 새 세션 키로 옮긴다.
            tokens.hand_over_session(user, previous_key, session.session_key)
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
    """웹 로그아웃. 이 세션이 발급한 확장 토큰도 폐기한다(다른 세션의 연결은 남긴다)."""
    require_csrf(request)
    with transaction.atomic():
        if request.user.is_authenticated:
            _lock_user(request.user)
            tokens.revoke_session(request.user, request._request.session.session_key)
        # 세션 행도 같은 트랜잭션에서 지워, 기다리던 토큰 발급이 끝난 세션을 보게 한다.
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


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def issue_extension_token(request):
    """로그인한 웹 세션이 확장에 넘길 토큰을 발급한다. 원본은 이 응답에만 있다."""
    require_csrf(request)
    if not request.user.is_authenticated:
        raise BusinessError(AuthError.LOGIN_REQUIRED, "로그인하지 않은 세션")
    session = request._request.session
    with transaction.atomic():
        # 같은 세션의 로그아웃이 먼저 끝났으면 세션이 없다. 그 세션 이름으로 토큰을 남기지 않는다.
        _lock_user(request.user)
        if not session.exists(session.session_key):
            raise BusinessError(AuthError.LOGIN_REQUIRED, "로그아웃한 세션")
        token = tokens.issue(request.user, session.session_key)
    # account: 확장이 다른 계정의 연결인지 가릴 때 쓰는 바뀌지 않는 식별자(이메일은 바뀌거나
    # 겹칠 수 있다).
    return Response({"token": token, "account": str(request.user.pk)}, status=201)


@api_view(["POST"])
@authentication_classes([tokens.ExtensionTokenRevocation])
@permission_classes([])
def revoke_extension_token(request):
    """확장 로그아웃: 요청한 토큰만 폐기한다. 웹 세션과 다른 토큰은 그대로다."""
    tokens.revoke(request.auth)
    return Response(status=204)
