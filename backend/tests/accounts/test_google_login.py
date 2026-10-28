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


def login(web, credential="google-id-token", age_confirmed=True):
    """age_confirmed: 로그인 카드의 '만 14세 이상' 확인(#251). 처음 가입할 때만 본다."""
    body = {"credential": credential}
    if age_confirmed is not None:
        body["age_confirmed"] = age_confirmed
    return web.post(
        "/api/auth/google/",
        body,
        content_type="application/json",
        **csrf(web),
    )


def test_first_google_login_creates_user_and_starts_session(web, google_says):
    calls = google_says(claims())

    response = login(web)

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "email": "me@example.com",
            "account": str(User.objects.get(email="me@example.com").pk),
        }
    }
    # 검증에 받은 토큰과 우리 클라이언트 ID를 넘긴다.
    assert calls == [{"token": "google-id-token", "audience": CLIENT_ID}]
    user = User.objects.get()
    assert (user.google_sub, user.email) == ("1234567890", "me@example.com")
    assert not user.has_usable_password()
    assert not user.is_staff
    assert web.get("/api/auth/me/").json() == {
        "user": {
            "email": "me@example.com",
            "account": str(User.objects.get(email="me@example.com").pk),
        }
    }


def test_same_google_account_logs_in_as_existing_user_and_updates_email(web, google_says):
    google_says(claims(email="old@example.com"))
    login(web)
    web.post("/api/auth/logout/", **csrf(web))
    google_says(claims(email="new@example.com"))

    response = login(web)

    assert response.json() == {
        "user": {
            "email": "new@example.com",
            "account": str(User.objects.get(email="new@example.com").pk),
        }
    }
    assert User.objects.get().email == "new@example.com"


@pytest.mark.parametrize(
    "result, code",
    [
        (ValueError("Token expired"), "AUTH:GOOGLE_TOKEN_INVALID"),
        (google_exceptions.InvalidValue("wrong aud"), "AUTH:GOOGLE_TOKEN_INVALID"),
        (claims(email_verified=False), "AUTH:EMAIL_NOT_VERIFIED"),
        (google_exceptions.TransportError("no certs"), "AUTH:GOOGLE_UNAVAILABLE"),
    ],
)
def test_failed_verification_is_rejected_without_creating_user(web, google_says, result, code):
    google_says(result)

    response = login(web)

    assert response.json() == {"error": code}
    assert not User.objects.exists()
    assert web.get("/api/auth/me/").json() == {"user": None}


def test_login_is_refused_when_client_id_is_not_set(web, google_says, settings):
    settings.GOOGLE_CLIENT_ID = ""
    calls = google_says(claims())

    response = login(web)

    assert (response.status_code, response.json()) == (503, {"error": "AUTH:LOGIN_UNAVAILABLE"})
    assert calls == []


def test_disabled_account_cannot_log_in(web, google_says):
    google_says(claims())
    login(web)
    User.objects.update(is_active=False)
    web.post("/api/auth/logout/", **csrf(web))

    assert login(web).json() == {"error": "AUTH:ACCOUNT_DISABLED"}
    assert web.get("/api/auth/me/").json() == {"user": None}


def test_logout_ends_session(web, google_says):
    google_says(claims())
    login(web)

    response = web.post("/api/auth/logout/", **csrf(web))

    assert response.json() == {"user": None}
    assert web.get("/api/auth/me/").json() == {"user": None}


def test_login_and_logout_without_csrf_are_refused(web, google_says):
    google_says(claims())
    web.get("/api/auth/me/")

    response = web.post("/api/auth/google/", {"credential": "t"}, content_type="application/json")

    assert (response.status_code, response.json()) == (403, {"error": "AUTH:CSRF_FAILED"})
    assert not User.objects.exists()

    login(web)
    response = web.post("/api/auth/logout/")

    assert (response.status_code, response.json()) == (403, {"error": "AUTH:CSRF_FAILED"})
    assert web.get("/api/auth/me/").json() == {
        "user": {
            "email": "me@example.com",
            "account": str(User.objects.get(email="me@example.com").pk),
        }
    }


@pytest.mark.parametrize("body", ['["google-id-token"]', '"google-id-token"', "null"])
def test_body_that_is_not_an_object_is_rejected_as_invalid_token(web, google_says, body):
    calls = google_says(claims())

    response = web.post("/api/auth/google/", body, content_type="application/json", **csrf(web))

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:GOOGLE_TOKEN_INVALID"})
    assert calls == []


def test_google_sub_longer_than_username_limit_still_logs_in(web, google_says):
    # OIDC sub는 255자까지 될 수 있고 username은 150자까지다.
    google_says(claims(sub="9" * 255))

    response = login(web)

    assert response.json() == {
        "user": {
            "email": "me@example.com",
            "account": str(User.objects.get(email="me@example.com").pk),
        }
    }
    assert User.objects.get().google_sub == "9" * 255


@pytest.mark.parametrize("age_confirmed", [None, False, "true"])
def test_first_login_without_age_confirmation_creates_no_account(web, google_says, age_confirmed):
    google_says(claims())

    response = login(web, age_confirmed=age_confirmed)

    assert (response.status_code, response.json()) == (403, {"error": "AUTH:AGE_NOT_CONFIRMED"})
    assert not User.objects.exists()
    assert web.get("/api/auth/me/").json() == {"user": None}


def test_existing_account_logs_in_without_age_confirmation(web, google_says):
    google_says(claims(email="old@example.com"))
    login(web)
    web.post("/api/auth/logout/", **csrf(web))
    google_says(claims(email="new@example.com"))

    response = login(web, age_confirmed=None)

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "new@example.com"
    assert User.objects.get().email == "new@example.com"
