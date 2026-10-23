"""Google ID 토큰 검증. 클라이언트 비밀값 없이 클라이언트 ID(aud)만으로 검증한다."""

from dataclasses import dataclass

from django.conf import settings
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from errors.auth import AuthError
from errors.base import BusinessError


@dataclass(frozen=True)
class GoogleAccount:
    sub: str
    email: str


def verify(credential):
    """ID 토큰의 서명·만료·aud·iss를 검증하고 인증된 이메일의 계정을 돌려준다."""
    # aud를 비워 두면 라이브러리가 aud를 검사하지 않으므로, 설정이 없으면 거부한다.
    if not settings.GOOGLE_CLIENT_ID:
        raise BusinessError(AuthError.LOGIN_UNAVAILABLE, "GOOGLE_CLIENT_ID 없음")
    if not isinstance(credential, str) or not credential:
        raise BusinessError(AuthError.GOOGLE_TOKEN_INVALID, "ID 토큰 없음")
    try:
        claims = id_token.verify_oauth2_token(
            credential, google_requests.Request(), audience=settings.GOOGLE_CLIENT_ID
        )
    except google_exceptions.TransportError as e:
        raise BusinessError(AuthError.GOOGLE_UNAVAILABLE, "Google 공개 키 받기 실패") from e
    except (ValueError, google_exceptions.GoogleAuthError) as e:
        raise BusinessError(AuthError.GOOGLE_TOKEN_INVALID, "ID 토큰 검증 실패") from e
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise BusinessError(AuthError.EMAIL_NOT_VERIFIED, "인증되지 않은 이메일")
    return GoogleAccount(sub=claims["sub"], email=claims["email"])
