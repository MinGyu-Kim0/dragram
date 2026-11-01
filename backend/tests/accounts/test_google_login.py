"""Google ID 토큰 로그인과 웹 세션(#92). Google 검증은 라이브러리 호출만 모킹한다."""

from datetime import date
from unittest.mock import ANY

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client
from google.auth import exceptions as google_exceptions

from accounts import google, views

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


def google_login(web, credential="google-id-token"):
    """가입 화면이 나오면 그 화면의 가입 식별자를 web.signup_id에 둔다."""
    response = web.post(
        "/api/auth/google/",
        {"credential": credential},
        content_type="application/json",
        **csrf(web),
    )
    if response.status_code == 200 and response.json().get("signup"):
        web.signup_id = response.json()["signup"]["id"]
    return response


def signup(web, body=None):
    """가입 화면의 '가입하기'. 기본은 마지막 가입 화면에서 이용약관에 동의한 요청이다."""
    return web.post(
        "/api/auth/signup/",
        {"agree_terms": True, "signup": getattr(web, "signup_id", None)} if body is None else body,
        content_type="application/json",
        **csrf(web),
    )


def login(web, credential="google-id-token"):
    """Google 로그인하고, 가입 화면이 나오면 약관에 동의해 가입한다. 마지막 응답을 돌려준다."""
    response = google_login(web, credential)
    if response.status_code == 200 and "signup" in response.json():
        return signup(web)
    return response


def test_first_google_login_creates_no_user_and_asks_to_sign_up(web, google_says):
    calls = google_says(claims())

    response = google_login(web)

    assert response.status_code == 200
    assert response.json() == {"user": None, "signup": {"email": "me@example.com", "id": ANY}}
    # 검증에 받은 토큰과 우리 클라이언트 ID를 넘긴다.
    assert calls == [{"token": "google-id-token", "audience": CLIENT_ID}]
    # 약관에 동의하기 전에는 계정도 이메일도 남기지 않고, 로그인 상태도 아니다.
    assert not User.objects.exists()
    assert web.get("/api/auth/me/").json() == {"user": None}


def test_signing_up_with_terms_agreed_creates_user_and_starts_session(web, google_says):
    google_says(claims())
    google_login(web)

    response = signup(web)

    assert response.status_code == 200
    user = User.objects.get()
    assert response.json() == {"user": {"email": "me@example.com", "account": str(user.pk)}}
    assert (user.google_sub, user.email) == ("1234567890", "me@example.com")
    assert not user.has_usable_password()
    assert not user.is_staff
    # 버전은 서버가 정한다. 처리방침 버전은 동의가 아니라 가입 때 보여 준 판이다.
    assert user.terms_version == date(2026, 11, 2)
    assert user.privacy_version == date(2026, 11, 2)
    assert user.terms_agreed_at is not None
    assert web.get("/api/auth/me/").json() == response.json()


@pytest.mark.parametrize("body", [{}, {"agree_terms": False}, {"agree_terms": "true"}, []])
def test_signup_without_terms_agreement_is_refused(web, google_says, body):
    google_says(claims())
    google_login(web)

    response = signup(web, body)

    assert (response.status_code, response.json()) == (400, {"error": "AUTH:TERMS_NOT_AGREED"})
    assert not User.objects.exists()
    assert web.get("/api/auth/me/").json() == {"user": None}
    # 거부해도 기다리던 가입은 남아, 체크하고 다시 누르면 된다.
    assert signup(web).status_code == 200


def test_waiting_signup_leaves_nothing_in_the_database(web, google_says):
    # 동의하지 않고 나간 사람의 이메일·Google 식별자는 세션 행에도 남기지 않는다.
    google_says(claims(sub="sub-not-stored", email="left@example.com"))

    google_login(web)

    assert not any(
        "left@example.com" in str(s.get_decoded()) or "sub-not-stored" in str(s.get_decoded())
        for s in Session.objects.all()
    )


def test_signup_without_a_verified_google_login_is_refused(web):
    # 요청 본문의 이메일·sub는 믿지 않는다. 세션에 검증한 Google 정보가 있어야 한다.
    response = signup(web, {"agree_terms": True, "email": "me@example.com", "sub": "1"})

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:SIGNUP_EXPIRED"})
    assert not User.objects.exists()


def test_signup_after_the_wait_expired_is_refused(web, google_says, monkeypatch):
    monkeypatch.setattr(views, "SIGNUP_WAIT_SECONDS", -1)
    google_says(claims())
    google_login(web)

    response = signup(web)

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:SIGNUP_EXPIRED"})
    assert not User.objects.exists()


def test_signup_uses_only_the_verified_google_account(web, google_says):
    google_says(claims(sub="real-sub", email="real@example.com"))
    google_login(web)

    signup(
        web,
        {"agree_terms": True, "signup": web.signup_id, "email": "evil@example.com", "sub": "o"},
    )

    assert User.objects.values_list("google_sub", "email").get() == ("real-sub", "real@example.com")


@pytest.mark.parametrize("shown", [None, "other"])
def test_signup_for_another_account_than_the_one_shown_is_refused(web, google_says, shown):
    # 탭 A에 A의 가입 화면이 떠 있는 사이 탭 B에서 B로 Google 로그인하면 쿠키가 B로 바뀐다.
    # A 화면의 '가입하기'가 B 계정을 만들지 않게, 화면이 받은 가입 식별자와 대조한다.
    google_says(claims(sub="a", email="a@example.com"))
    google_login(web)
    shown_id = web.signup_id if shown is None else shown
    google_says(claims(sub="b", email="b@example.com"))
    google_login(web)

    response = signup(web, {"agree_terms": True, "signup": shown_id})

    assert (response.status_code, response.json()) == (409, {"error": "AUTH:ACCOUNT_MISMATCH"})
    assert not User.objects.exists()
    # 지금 화면(B)으로는 가입할 수 있다.
    assert signup(web).json()["user"]["email"] == "b@example.com"


def test_signup_without_csrf_is_refused(web, google_says):
    google_says(claims())
    google_login(web)

    response = web.post("/api/auth/signup/", {"agree_terms": True}, content_type="application/json")

    assert (response.status_code, response.json()) == (403, {"error": "AUTH:CSRF_FAILED"})
    assert not User.objects.exists()


def test_signup_is_used_once(web, google_says):
    google_says(claims())
    login(web)
    web.post("/api/auth/logout/", **csrf(web))

    response = signup(web)

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:SIGNUP_EXPIRED"})
    assert User.objects.count() == 1


def test_existing_account_without_agreement_goes_through_signup(web, google_says):
    # 가입 화면 전에 만든 운영자·테스트 계정. 같은 행에 동의 기록을 채운다.
    old = User.objects.create(username="old", email="old@example.com", google_sub="1234567890")
    google_says(claims(email="new@example.com"))

    response = google_login(web)

    assert response.json() == {"user": None, "signup": {"email": "new@example.com", "id": ANY}}
    assert web.get("/api/auth/me/").json() == {"user": None}

    response = signup(web)

    assert response.json() == {"user": {"email": "new@example.com", "account": str(old.pk)}}
    user = User.objects.get()
    assert user.pk == old.pk
    assert user.email == "new@example.com"
    assert user.terms_agreed_at is not None


def test_new_google_account_ends_the_session_of_the_previous_user(web, google_says):
    google_says(claims(sub="first", email="first@example.com"))
    login(web)
    google_says(claims(sub="second", email="second@example.com"))

    response = google_login(web)

    assert response.json() == {"user": None, "signup": {"email": "second@example.com", "id": ANY}}
    assert web.get("/api/auth/me/").json() == {"user": None}


def test_same_google_account_logs_in_as_existing_user_and_updates_email(web, google_says):
    google_says(claims(email="old@example.com"))
    login(web)
    web.post("/api/auth/logout/", **csrf(web))
    google_says(claims(email="new@example.com"))

    # 이미 동의한 계정은 가입 화면 없이 바로 로그인한다.
    response = google_login(web)

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
