"""확장 토큰 발급과 Bearer 인증(#109)."""

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from accounts.models import ExtensionToken
from errors.auth import AuthError
from errors.base import BusinessError

# 마지막 사용 후 이 기간이 지나면 쓸 수 없다. 재발급·갱신은 없다. 마지막 사용 시각은 하루에
# 한 번만 바꾸므로 날짜로 센다(그날 늦게 또 썼을 수 있다).
EXPIRES_AFTER = timedelta(days=90)


def lock_user(user_id):
    """같은 사용자의 토큰 발급·첫 사용 정리와 웹 로그인·로그아웃을 직렬화한다(트랜잭션 안에서)."""
    User = ExtensionToken._meta.get_field("user").related_model
    User.objects.select_for_update().filter(pk=user_id).first()


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue(user, session_key):
    """새 토큰을 만들어 원본을 돌려준다. 원본은 저장하지 않는다.

    같은 세션(같은 브라우저의 확장)이 발급하고 아직 한 번도 쓰지 않은 토큰은 지운다. 쓰던
    토큰은 새 토큰이 처음 쓰일 때 지운다(확장에 새 토큰을 넘기지 못해도 쓰던 연결은 남는다).
    그래서 세션마다 쓰던 토큰과 기다리는 토큰, 많아야 둘만 남는다.
    """
    ExtensionToken.objects.filter(
        user=user, session_key=session_key, last_used_at__isnull=True
    ).delete()
    token = secrets.token_urlsafe(32)
    ExtensionToken.objects.create(token_hash=_hash(token), user=user, session_key=session_key)
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


def hand_over_session(user, old_key, new_key):
    """세션에 user가 로그인했다. old_key 세션이 발급한 토큰 가운데 다른 사용자 것은 폐기하고,
    user 것은 new_key로 옮긴다(같은 사용자가 다시 로그인해 세션 키가 바뀐 경우).
    """
    from_old = ExtensionToken.objects.filter(session_key=old_key)
    from_old.exclude(user=user).filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    if old_key != new_key:
        from_old.filter(user=user).update(session_key=new_key)


def _usable_row(request, *, allow_inactive=False):
    """Bearer 토큰의 행. 없거나 폐기·만료됐으면 AUTH:LOGIN_REQUIRED다."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not token:
        raise BusinessError(AuthError.LOGIN_REQUIRED, "토큰 없음")
    row = (
        ExtensionToken.objects.select_related("user")
        .filter(token_hash=_hash(token), revoked_at__isnull=True)
        .first()
    )
    today = timezone.localdate()
    if (
        row is None
        or timezone.localdate(row.last_used_at or row.created_at) < today - EXPIRES_AFTER
        or not (row.user.is_active or allow_inactive)
    ):
        raise BusinessError(AuthError.LOGIN_REQUIRED, "쓸 수 없는 토큰")
    return row


class ExtensionTokenAuthentication(BaseAuthentication):
    """Authorization: Bearer <토큰>. 토큰이 없거나 쓸 수 없으면 AUTH:LOGIN_REQUIRED다.

    이 인증을 쓰는 API는 로그인이 필수라, 토큰이 없을 때도 다음 인증으로 넘기지 않고 거부한다.
    """

    def authenticate(self, request):
        row = _usable_row(request)
        now = timezone.now()
        if row.last_used_at is None:
            # 처음 쓰였다. 같은 세션의 다른(예전) 토큰을 지운다. 재발급과 겹치면 방금 발급한
            # 토큰을 지울 수 있어 발급과 같은 잠금 안에서 하고, 그사이 이 토큰이 지워졌으면
            # (재발급이 쓰지 않은 토큰을 지웠다) 거부한다.
            with transaction.atomic():
                lock_user(row.user_id)
                # 잠근 뒤 다시 읽는다. 같은 토큰의 다른 요청이 먼저 첫 사용을 마쳤으면(그 뒤
                # 재발급된 토큰이 있을 수 있다) 정리하지 않는다.
                fresh = ExtensionToken.objects.filter(pk=row.pk, revoked_at__isnull=True).first()
                if fresh is None:
                    raise BusinessError(AuthError.LOGIN_REQUIRED, "그사이 바뀐 토큰")
                if fresh.last_used_at is None:
                    ExtensionToken.objects.filter(
                        user=row.user, session_key=row.session_key
                    ).exclude(pk=row.pk).delete()
                    ExtensionToken.objects.filter(pk=row.pk).update(last_used_at=now)
        # 마지막 사용 시각은 하루에 한 번만 바꾼다.
        elif timezone.localdate(row.last_used_at) != timezone.localdate(now):
            ExtensionToken.objects.filter(pk=row.pk).update(last_used_at=now)
        return (row.user, row)

    def authenticate_header(self, request):
        return "Bearer"


class ExtensionTokenRevocation(BaseAuthentication):
    """확장 로그아웃(토큰 폐기) 전용. 막힌 계정의 토큰도 찾아 폐기할 수 있게 한다."""

    def authenticate(self, request):
        row = _usable_row(request, allow_inactive=True)
        return (row.user, row)

    def authenticate_header(self, request):
        return "Bearer"
