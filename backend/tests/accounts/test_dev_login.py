"""로컬 수동 확인용 개발 로그인과 admin 로그인(#92)."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

pytestmark = pytest.mark.django_db

User = get_user_model()


def dev_login(client, email="dev@example.com"):
    return client.post("/api/auth/dev-login/", {"email": email}, content_type="application/json")


def test_dev_login_works_only_with_flag_in_debug(client, settings):
    settings.DEBUG = True
    settings.DEV_LOGIN_ENABLED = True

    response = dev_login(client)

    assert response.json() == {
        "user": {
            "email": "dev@example.com",
            "account": str(User.objects.get(email="dev@example.com").pk),
        }
    }
    assert client.get("/api/auth/me/").json() == {
        "user": {
            "email": "dev@example.com",
            "account": str(User.objects.get(email="dev@example.com").pk),
        }
    }
    user = User.objects.get()
    assert user.google_sub is None
    assert not user.has_usable_password()


@pytest.mark.parametrize("debug, enabled", [(True, False), (False, True), (False, False)])
def test_dev_login_is_not_found_otherwise(client, settings, debug, enabled):
    settings.DEBUG = debug
    settings.DEV_LOGIN_ENABLED = enabled

    assert dev_login(client).status_code == 404
    assert not User.objects.exists()


def test_dev_login_requires_csrf(settings):
    settings.DEBUG = True
    settings.DEV_LOGIN_ENABLED = True
    web = Client(enforce_csrf_checks=True)

    response = dev_login(web)

    assert response.json() == {"error": "AUTH:CSRF_FAILED"}


def test_superuser_from_createsuperuser_can_use_admin(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "admin-test-password")
    call_command("createsuperuser", username="admin", email="admin@example.com", interactive=False)
    client = Client()

    assert client.login(username="admin", password="admin-test-password")
    assert client.get("/admin/accounts/user/").status_code == 200


@pytest.mark.parametrize("body", ['["dev@example.com"]', '"dev@example.com"'])
def test_dev_login_body_that_is_not_an_object_is_rejected(client, settings, body):
    settings.DEBUG = True
    settings.DEV_LOGIN_ENABLED = True

    response = client.post("/api/auth/dev-login/", body, content_type="application/json")

    assert (response.status_code, response.json()) == (400, {"error": "AUTH:DEV_EMAIL_INVALID"})


@pytest.mark.parametrize("email", [123, None, "not-an-email", "a" * 140 + "@example.com"])
def test_dev_login_rejects_values_that_are_not_usable_emails(client, settings, email):
    settings.DEBUG = True
    settings.DEV_LOGIN_ENABLED = True

    assert dev_login(client, email).json() == {"error": "AUTH:DEV_EMAIL_INVALID"}
    assert not User.objects.exists()
