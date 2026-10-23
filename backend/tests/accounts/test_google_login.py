"""Google ID 토큰 로그인과 웹 세션(#92). Google 검증은 라이브러리 호출만 모킹한다."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from google.auth import exceptions as google_exceptions

from accounts import google

pytestmark = pytest.mark.django_db

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
User = get_user_model()


@pytest.fixture(autouse=True)
def client_id(settings):
    settings.GOOGLE_CLIENT_ID = CLIENT_ID


@pytest.fixture
def google_says(monkeypatch):
    """Google 검증 결과를 정한다. claims(dict)를 돌려주거나 예외를 낸다. 받은 인자를 남긴다."""
    calls = []

    def set_result(result):
        def verify(token, request, audience):
            calls.append({"token": token, "audience": audience})
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(google.id_token, "verify_oauth2_token", verify)
        return calls

    return set_result


def claims(sub="1234567890", email="me@example.com", email_verified=True):
    return {"sub": sub, "email": email, "email_verified": email_verified}


@pytest.fixture
def web():
    """CSRF를 검사하는 브라우저. 현재 사용자 조회로 CSRF 쿠키를 받는다."""
    return Client(enforce_csrf_checks=True)


def csrf(web):
    web.get("/api/auth/me/")
    return {"HTTP_X_CSRFTOKEN": web.cookies["csrftoken"].value}


def login(web, credential="google-id-token"):
    return web.post(
        "/api/auth/google/", {"credential": credential}, content_type="application/json", **csrf(web)
    )


def test_first_google_login_creates_user_and_starts_session(web, google_says):
    calls = google_says(claims())

    response = login(web)

    assert response.status_code == 200
    assert response.json() == {"user": {"email": "me@example.com"}}
    # 검증에 받은 토큰과 우리 클라이언트 ID를 넘긴다.
    assert calls == [{"token": "google-id-token", "audience": CLIENT_ID}]
    user = User.objects.get()
    assert (user.google_sub, user.email) == ("1234567890", "me@example.com")
    assert not user.has_usable_password()
    assert not user.is_staff
    assert web.get("/api/auth/me/").json() == {"user": {"email": "me@example.com"}}
