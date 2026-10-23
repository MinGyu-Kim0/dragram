"""확장 토큰 발급과 Bearer 인증(#109)."""

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from accounts.models import ExtensionToken
from errors.auth import AuthError
from errors.base import BusinessError

# 마지막 사용 후 이 기간이 지나면 쓸 수 없다. 재발급·갱신은 없다. 마지막 사용 시각은 하루에
# 한 번만 바꾸므로 날짜로 센다(그날 늦게 또 썼을 수 있다).
EXPIRES_AFTER = timedelta(days=90)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue(user, session_key):
    """새 토큰을 만들어 원본을 돌려준다. 원본은 저장하지 않는다."""
    token = secrets.token_urlsafe(32)
    ExtensionToken.objects.create(
        token_hash=_hash(token),
        user=user,
        session_key=session_key,
        last_used_at=timezone.now(),
    )
    return token


def revoke(token_row):
    ExtensionToken.objects.filter(pk=token_row.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def revoke_session(user, session_key):
    """이 웹 로그인 세션이 발급한 토큰을 모두 폐기한다."""
    ExtensionToken.objects.filter(
        user=user, session_key=session_key, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())


class ExtensionTokenAuthentication(BaseAuthentication):
    """Authorization: Bearer <토큰>. 토큰이 없거나 쓸 수 없으면 AUTH:LOGIN_REQUIRED다.

    이 인증을 쓰는 API는 로그인이 필수라, 토큰이 없을 때도 다음 인증으로 넘기지 않고 거부한다.
    """

    def authenticate(self, request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme != "Bearer" or not token:
            raise BusinessError(AuthError.LOGIN_REQUIRED, "토큰 없음")
        row = (
            ExtensionToken.objects.select_related("user")
            .filter(token_hash=_hash(token), revoked_at__isnull=True)
            .first()
        )
        now = timezone.now()
        today = timezone.localdate(now)
        if (
            row is None
            or timezone.localdate(row.last_used_at) < today - EXPIRES_AFTER
            or not row.user.is_active
        ):
            raise BusinessError(AuthError.LOGIN_REQUIRED, "쓸 수 없는 토큰")
        # 마지막 사용 시각은 하루에 한 번만 바꾼다.
        if timezone.localdate(row.last_used_at) != today:
            ExtensionToken.objects.filter(pk=row.pk).update(last_used_at=now)
        return (row.user, row)

    def authenticate_header(self, request):
        return "Bearer"
