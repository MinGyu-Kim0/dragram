"""웹 로그인 세션 API. 웹과 API는 같은 출처에서 Django 세션·CSRF를 쓴다(#92)."""

import uuid
from datetime import date

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.hashers import make_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import Http404
from django.middleware.csrf import CsrfViewMiddleware
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts import google, tokens, withdrawal
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
    tokens.lock_user(getattr(user_or_id, "pk", user_or_id))


def _user_body(user):
    # account: 바뀌지 않는 계정 식별자. 화면에 보인 계정으로 탈퇴하는지 서버가 대조할 때 쓴다.
    if not user.is_authenticated:
        return {"user": None}
    return {"user": {"email": user.email, "account": str(user.pk)}}


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


# 가입을 기다리는 동안 검증한 Google 계정을 담는 서명한 쿠키. 이 시간 안에 '가입하기'를 눌러야 한다.
# 세션(DB 행)에 두지 않아, 동의하지 않고 나간 사람의 이메일·sub가 서버에 남지 않는다.
SIGNUP_COOKIE = "dragram_signup"
SIGNUP_SALT = "accounts.signup"
SIGNUP_WAIT_SECONDS = 10 * 60
# 가입할 때 기록하는 판. 웹 TermsPage·PrivacyPage의 최신 시행일과 맞춘다.
TERMS_VERSION = date(2026, 10, 29)
PRIVACY_VERSION = date(2026, 10, 29)


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def google_login(request):
    """Google ID 토큰으로 로그인한다. 이메일은 매번 갱신한다.

    이용약관에 동의한 계정만 바로 로그인한다. 처음 온 사람과 동의 기록이 없는 계정은 계정을
    만들거나 고치지 않고, 검증한 Google 계정을 서명한 쿠키에 잠시 둔 채 가입 화면을 보이게
    한다(#257).
    """
    require_csrf(request)
    account = google.verify(_field(request, "credential", AuthError.GOOGLE_TOKEN_INVALID))
    user = User.objects.filter(google_sub=account.sub).first()
    if user is not None and not user.is_active:
        raise BusinessError(AuthError.ACCOUNT_DISABLED, "막힌 계정")
    # update가 0이면 그사이 탈퇴한 계정이다. 동의 없이 새로 만들지 않도록 가입 화면으로 보낸다.
    if (
        user is not None
        and user.terms_agreed_at is not None
        and User.objects.filter(pk=user.pk).update(email=account.email)
    ):
        user.email = account.email
        response = _start_session(request, user)
        response.delete_cookie(SIGNUP_COOKIE)
        return response
    # 계정이 없으면 로그인 상태가 아니다. 이전 사용자의 세션은 로그아웃처럼 끝낸다.
    _end_session(request)
    # id: 이 가입 화면의 식별자. 쿠키는 탭끼리 공유하므로, 가입하기가 화면에 보인 계정인지 대조한다.
    pending = {"sub": account.sub, "email": account.email, "id": uuid.uuid4().hex}
    response = Response({"user": None, "signup": {"email": account.email, "id": pending["id"]}})
    response.set_cookie(
        SIGNUP_COOKIE,
        signing.dumps(pending, salt=SIGNUP_SALT),
        max_age=SIGNUP_WAIT_SECONDS,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )
    return response


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def signup(request):
    """가입하기: 이용약관에 동의하면 쿠키에 둔 검증한 Google 계정으로 계정을 만들고 로그인한다.

    본문의 이메일·sub는 보지 않는다. 동의 기록이 없던 기존 계정은 그 행에 기록을 채운다.
    본문의 signup은 가입 화면이 받은 식별자다. 그사이 다른 탭에서 다른 계정으로 Google 로그인해
    쿠키가 바뀌었으면, 화면에 보이지 않은 계정을 만들지 않고 거부한다.
    """
    require_csrf(request)
    try:
        # 서명 시각부터 센다. 쿠키 만료를 믿지 않고 서버가 다시 본다.
        pending = signing.loads(
            request.COOKIES.get(SIGNUP_COOKIE, ""),
            salt=SIGNUP_SALT,
            max_age=SIGNUP_WAIT_SECONDS,
        )
    except signing.BadSignature as e:
        raise BusinessError(AuthError.SIGNUP_EXPIRED, "검증한 Google 로그인이 없거나 만료") from e
    if _field(request, "agree_terms", AuthError.TERMS_NOT_AGREED) is not True:
        raise BusinessError(AuthError.TERMS_NOT_AGREED, "이용약관 동의 없음")
    if request.data.get("signup") != pending["id"]:
        raise BusinessError(AuthError.ACCOUNT_MISMATCH, "가입 화면의 계정과 쿠키의 계정이 다름")
    agreement = {
        "email": pending["email"],
        "terms_version": TERMS_VERSION,
        "privacy_version": PRIVACY_VERSION,
        "terms_agreed_at": timezone.now(),
    }
    # 막힌 계정이라 로그인하지 못하면 동의 기록도 되돌린다.
    with transaction.atomic():
        user, _ = User.objects.update_or_create(
            google_sub=pending["sub"],
            defaults=agreement,
            create_defaults={
                **agreement,
                # sub는 255자까지 될 수 있어 150자 username에 넣지 않는다.
                "username": f"google-{uuid.uuid4().hex}",
                "password": make_password(None),
            },
        )
        response = _start_session(request, user)
    response.delete_cookie(SIGNUP_COOKIE)
    return response


def _end_session(request):
    """웹 로그아웃. 이 세션이 발급한 확장 토큰도 폐기한다(다른 세션의 연결은 남긴다)."""
    with transaction.atomic():
        if request.user.is_authenticated:
            _lock_user(request.user)
            tokens.revoke_session(request.user, request._request.session.session_key)
        # 세션 행도 같은 트랜잭션에서 지워, 기다리던 토큰 발급이 끝난 세션을 보게 한다.
        auth.logout(request._request)


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def logout(request):
    """웹 로그아웃. 이 세션이 발급한 확장 토큰도 폐기한다(다른 세션의 연결은 남긴다)."""
    require_csrf(request)
    _end_session(request)
    return Response(_user_body(request._request.user))


@api_view(["POST"])
@authentication_classes([SessionUser])
@permission_classes([])
def withdraw(request):
    """회원 탈퇴. 지우는 범위는 withdrawal.withdraw가 정한다.

    본문의 account는 확인 화면에 보인 계정이다. 화면을 연 뒤 다른 탭에서 다른 계정으로 로그인했으면
    지금 세션의 계정을 지우지 않고 거부한다.
    """
    require_csrf(request)
    if not request.user.is_authenticated:
        raise BusinessError(AuthError.LOGIN_REQUIRED, "로그인하지 않은 세션")
    user = request.user
    if _field(request, "account", AuthError.ACCOUNT_MISMATCH) != str(user.pk):
        raise BusinessError(AuthError.ACCOUNT_MISMATCH, "확인한 계정과 세션 계정이 다름")
    with transaction.atomic():
        withdrawal.withdraw(user)
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
