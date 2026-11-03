"""관리 화면에서 사용자별 토큰 사용량 보기와 하루 한도 초기화(#386)."""

from datetime import timedelta

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone

from analysis import limits
from analysis.models import UsageLog

pytestmark = pytest.mark.django_db

User = get_user_model()
LOGS = "/admin/analysis/usagelog/"
WITHDRAWN_KEY = "f" * 64


def log(user=None, purpose="first_response", input_tokens=10, output_tokens=5, **fields):
    return UsageLog.objects.create(
        kind="llm",
        user=user,
        purpose=purpose,
        model="gpt-test",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        success=True,
        attempt=1,
        **fields,
    )


@pytest.fixture
def alice():
    return User.objects.create(username="alice", email="alice@example.com")


def test_usage_log_list_shows_tokens_per_user(admin_client, alice):
    log(alice, input_tokens=1234, output_tokens=567)
    log(None, purpose="usage_fill")
    log(None, withdrawn_key=WITHDRAWN_KEY)

    page = admin_client.get(LOGS).content.decode()

    assert "alice@example.com" in page
    assert "1234" in page and "567" in page
    assert "시스템" in page
    assert "탈퇴(오늘)" in page
    # 탈퇴한 Google 계정의 비교값은 어디에도 보이지 않는다.
    assert WITHDRAWN_KEY not in page


def test_usage_log_list_filters_by_purpose_and_finds_by_email(admin_client, alice):
    bob = User.objects.create(username="bob", email="bob@example.com")
    log(alice, purpose="reask")
    log(bob, purpose="word_gloss")

    by_purpose = admin_client.get(LOGS, {"purpose": "reask"}).content.decode()
    by_email = admin_client.get(LOGS, {"q": "bob@"}).content.decode()

    assert "alice@example.com" in by_purpose and "bob@example.com" not in by_purpose
    assert "bob@example.com" in by_email and "alice@example.com" not in by_email


def test_usage_log_cannot_be_added_changed_or_deleted(admin_client, alice):
    row = log(alice)

    assert admin_client.get(f"{LOGS}add/").status_code == 403
    assert admin_client.post(f"{LOGS}{row.pk}/change/", {"input_tokens": 0}).status_code == 403
    assert admin_client.post(f"{LOGS}{row.pk}/delete/", {"post": "yes"}).status_code == 403
    assert "delete_selected" not in admin_client.get(LOGS).content.decode()
    row.refresh_from_db()
    assert row.input_tokens == 10


def test_staff_without_the_view_permission_cannot_see_usage(alice):
    staff = User.objects.create(username="staff", is_staff=True)
    client = Client()
    client.force_login(staff)

    assert client.get(LOGS).status_code == 403

    staff.user_permissions.add(Permission.objects.get(codename="view_usagelog"))
    assert client.get(LOGS).status_code == 200


USERS = "/admin/accounts/user/"


def test_user_list_shows_and_sorts_by_todays_tokens(admin_client, alice):
    bob = User.objects.create(username="bob", email="bob@example.com")
    log(alice, input_tokens=100, output_tokens=11)
    log(bob, input_tokens=3000, output_tokens=0)
    # 한도와 같이 request 행과 어제 행은 세지 않는다.
    UsageLog.objects.create(kind="request", path="llm", user=alice, input_tokens=9, success=True)
    old = log(alice, input_tokens=5000)
    UsageLog.objects.filter(pk=old.pk).update(
        created_at=timezone.localtime().replace(hour=0, minute=0) - timedelta(minutes=1)
    )

    page = admin_client.get(USERS, {"o": "-6"}).content.decode()

    assert ">111<" in page and ">3000<" in page
    assert page.index("bob@example.com") < page.index("alice@example.com")


def test_user_page_shows_todays_tokens_against_the_limit(settings, admin_client, alice):
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1000
    log(alice, input_tokens=100, output_tokens=11)

    page = admin_client.get(f"{USERS}{alice.pk}/change/").content.decode()

    assert "111 / 1000" in page
    link = f"{LOGS}?user__id__exact={alice.pk}"
    assert link in page
    log(User.objects.create(username="bob", email="bob@example.com"))
    # 링크는 그 사용자의 기록만 보여 준다.
    logs = admin_client.get(link).content.decode()
    assert "alice@example.com" in logs and "bob@example.com" not in logs


def test_reset_action_restarts_the_daily_limit_but_keeps_the_records(admin_client, alice):
    log(alice, input_tokens=100, output_tokens=11)

    response = admin_client.post(
        USERS, {"action": "reset_usage", "_selected_action": [alice.pk]}, follow=True
    )

    assert response.status_code == 200
    alice.refresh_from_db()
    assert limits.today_tokens(alice) == 0
    assert UsageLog.objects.filter(user=alice).count() == 1
    # 누가 언제 초기화했는지 admin 기록에 남는다.
    assert LogEntry.objects.filter(object_id=str(alice.pk), change_message__contains="초기화")
