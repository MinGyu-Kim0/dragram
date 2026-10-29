"""회원 탈퇴: 웹 세션으로 본인 계정과 개인 기록을 지운다(#239)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from accounts import google
from accounts.models import ExtensionToken
from analysis import jobs, limits, usage
from analysis.models import DesignatedName, SentenceAnalysis, UsageLog, UserSentence
from tests.analysis.helpers import analyze, connected_client

pytestmark = pytest.mark.django_db

User = get_user_model()
WITHDRAW = "/api/auth/withdraw/"


def carried_rows():
    """탈퇴한 Google 계정의 그날 행. 한도 계산에 필요한 토큰 수·시각만 남아야 한다(#252)."""
    return UsageLog.objects.exclude(withdrawn_key=None)


def assert_only_tokens_and_time_are_kept():
    rows = carried_rows()
    assert rows.exists()
    assert not rows.exclude(analysis=None).exists()
    assert not rows.exclude(model=None).exists()
    assert not rows.exclude(attempt=None).exists()


def web_session(user):
    """그 사용자로 로그인한 웹 브라우저(CSRF 검사함)와 그 CSRF 헤더"""
    web = Client(enforce_csrf_checks=True)
    web.force_login(user)
    web.get("/api/auth/me/")
    return web, {"HTTP_X_CSRFTOKEN": web.cookies["csrftoken"].value}


def withdraw(web, headers, user):
    """화면에 보인 계정(user)으로 탈퇴를 확인해 보낸다."""
    return web.post(WITHDRAW, {"account": str(user.pk)}, content_type="application/json", **headers)


def google_login(web, monkeypatch, settings, sub):
    """Google 계정(sub)으로 웹에 로그인하고 그 계정을 돌려준다."""
    settings.GOOGLE_CLIENT_ID = "test-client-id"
    claims = {"sub": sub, "email": "me@example.com", "email_verified": True}
    monkeypatch.setattr(google.id_token, "verify_oauth2_token", lambda *args, **kwargs: claims)
    sign_up_with_google(web)
    return User.objects.get(google_sub=sub)


def sign_up_with_google(web):
    """Google 로그인 뒤 가입 화면에서 이용약관에 동의해 가입한다. 가입 응답을 돌려준다."""
    web.get("/api/auth/me/")

    def post(path, body):
        return web.post(
            path,
            body,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=web.cookies["csrftoken"].value,
        )

    shown = post("/api/auth/google/", {"credential": "google-id-token"}).json()["signup"]
    return post("/api/auth/signup/", {"agree_terms": True, "signup": shown["id"]})


def user_with_records(username, fake_llm):
    """분석 기록·지정한 이름·확장 토큰·사용량 기록이 있는 사용자와 그 확장 클라이언트"""
    client = connected_client(username)
    fake_llm.response = {"translation_ko": "학생입니다"}
    analyze(client, f"{username}は学生です。")
    client.put("/api/names/", {"surface": "春", "reading": "はる"}, content_type="application/json")
    return User.objects.get(username=username), client


def records_of(user):
    return {
        "sentences": UserSentence.objects.filter(user=user).count(),
        "names": DesignatedName.objects.filter(user=user).count(),
        "tokens": ExtensionToken.objects.filter(user=user).count(),
        "usage": UsageLog.objects.filter(user=user).count(),
    }


def test_withdrawal_deletes_the_account_and_its_personal_records(fake_llm):
    me, _ = user_with_records("me", fake_llm)
    other, _ = user_with_records("other", fake_llm)
    usage_before = UsageLog.objects.count()
    mine = records_of(me)
    others = records_of(other)
    analyses = SentenceAnalysis.objects.count()
    assert all(mine.values()) and all(others.values())
    web, headers = web_session(me)

    response = withdraw(web, headers, me)

    assert (response.status_code, response.json()) == (200, {"user": None})
    assert not User.objects.filter(pk=me.pk).exists()
    assert not UserSentence.objects.filter(original_text__startswith="me").exists()
    assert not ExtensionToken.objects.exclude(user=other).exists()
    # 사용량 행은 연결만 비우지 않고 지운다.
    assert UsageLog.objects.count() == usage_before - mine["usage"]
    assert records_of(other) == others
    assert SentenceAnalysis.objects.count() == analyses


def test_extension_cannot_analyze_after_withdrawal(fake_llm):
    me, extension = user_with_records("me", fake_llm)
    web, headers = web_session(me)

    withdraw(web, headers, me)

    response = extension.post(
        "/api/analyses/", {"text": "私は学生です。"}, content_type="application/json"
    )
    assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_withdrawal_needs_a_logged_in_session():
    web = Client(enforce_csrf_checks=True)
    web.get("/api/auth/me/")

    response = web.post(WITHDRAW, HTTP_X_CSRFTOKEN=web.cookies["csrftoken"].value)

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_withdrawal_without_csrf_is_refused_and_deletes_nothing():
    me = User.objects.create(username="me", email="me@example.com")
    web, _ = web_session(me)

    response = web.post(WITHDRAW)

    assert (response.status_code, response.json()) == (403, {"error": "AUTH:CSRF_FAILED"})
    assert User.objects.filter(pk=me.pk).exists()


def test_logging_in_again_with_the_same_google_account_starts_an_empty_account(
    fake_llm, monkeypatch, settings
):
    settings.GOOGLE_CLIENT_ID = "test-client-id"
    claims = {"sub": "google-sub-1", "email": "me@example.com", "email_verified": True}
    monkeypatch.setattr(google.id_token, "verify_oauth2_token", lambda *args, **kwargs: claims)
    me, _ = user_with_records("me", fake_llm)
    User.objects.filter(pk=me.pk).update(google_sub="google-sub-1")
    web, headers = web_session(me)
    withdraw(web, headers, me)

    response = sign_up_with_google(web)

    assert response.json() == {
        "user": {
            "email": "me@example.com",
            "account": str(User.objects.get(email="me@example.com").pk),
        }
    }
    again = User.objects.get(google_sub="google-sub-1")
    assert again.pk != me.pk
    assert not any(records_of(again).values())


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_withdrawal_during_an_analysis_leaves_no_record_behind(fake_llm, monkeypatch, settings):
    # 실제 커밋이 일어나야 외래키 검사가 돌므로 트랜잭션 테스트로 둔다.
    me = User.objects.create(username="me", email="me@example.com", google_sub="google-sub-1")
    extension = connected_client("me")
    web, headers = web_session(me)
    fake_llm.response = {"translation_ko": "학생입니다"}
    fake_llm.before_respond = lambda: withdraw(web, headers, me)

    analyze(extension, "私は学生です。")

    assert not User.objects.filter(pk=me.pk).exists()
    assert not UserSentence.objects.exists()
    assert not UsageLog.objects.filter(user_id=me.pk).exists()
    # 탈퇴한 뒤 끝난 LLM 호출도 같은 Google 계정의 그날 사용량에 든다.
    again = google_login(web, monkeypatch, settings, "google-sub-1")
    assert limits.today_tokens(again) == 110
    assert_only_tokens_and_time_are_kept()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_withdrawal_before_the_worker_starts_still_saves_the_shared_analysis(
    fake_llm, monkeypatch, settings
):
    # 같은 문장을 기다리는 다른 요청이 있을 수 있어 공용 분석은 끝까지 저장한다.
    me = User.objects.create(username="me", email="me@example.com", google_sub="google-sub-1")
    extension = connected_client("me")
    web, headers = web_session(me)
    fake_llm.response = {"translation_ko": "학생입니다"}
    enqueue = jobs.enqueue_analysis

    def withdraw_then_enqueue(*args):
        withdraw(web, headers, me)
        enqueue(*args)

    monkeypatch.setattr(jobs, "enqueue_analysis", withdraw_then_enqueue)

    analyze(extension, "私は学生です。")

    assert SentenceAnalysis.objects.get().status == SentenceAnalysis.Status.COMPLETE
    assert not UserSentence.objects.exists()
    assert not UsageLog.objects.exclude(user=None).exists()
    again = google_login(web, monkeypatch, settings, "google-sub-1")
    assert limits.today_tokens(again) == 110
    assert_only_tokens_and_time_are_kept()


@pytest.mark.parametrize("account", [None, "other"])
def test_withdrawal_for_another_account_than_the_session_is_refused(account):
    # 화면을 연 뒤 다른 탭에서 다른 계정으로 로그인했으면, 화면에 보인 계정과 세션 계정이 다르다.
    me = User.objects.create(username="me", email="me@example.com")
    other = User.objects.create(username="other", email="other@example.com")
    web, headers = web_session(me)
    body = {} if account is None else {"account": str(other.pk)}

    response = web.post(WITHDRAW, body, content_type="application/json", **headers)

    assert (response.status_code, response.json()) == (409, {"error": "AUTH:ACCOUNT_MISMATCH"})
    assert User.objects.filter(pk=me.pk).exists()


def test_signing_up_again_the_same_day_keeps_the_days_usage(fake_llm, monkeypatch, settings):
    # 탈퇴·재가입으로 하루 한도를 새로 받지 못하게 한다(PR #244 보안 리뷰).
    me, _ = user_with_records("me", fake_llm)
    User.objects.filter(pk=me.pk).update(google_sub="google-sub-1")
    used = limits.today_tokens(me)
    assert used > 0
    web, headers = web_session(me)
    withdraw(web, headers, me)

    again = google_login(web, monkeypatch, settings, "google-sub-1")

    assert limits.today_tokens(again) == used
    # 남은 행은 계정과 이어지지 않고, Google 계정 식별자도 그대로 남지 않는다.
    assert not UsageLog.objects.filter(user_id=me.pk).exists()
    assert not UsageLog.objects.filter(withdrawn_key="google-sub-1").exists()
    assert_only_tokens_and_time_are_kept()


def test_another_google_account_does_not_get_the_withdrawn_usage(fake_llm, monkeypatch, settings):
    me, _ = user_with_records("me", fake_llm)
    User.objects.filter(pk=me.pk).update(google_sub="google-sub-1")
    web, headers = web_session(me)
    withdraw(web, headers, me)

    other = google_login(web, monkeypatch, settings, "google-sub-2")

    assert limits.today_tokens(other) == 0


def test_withdrawn_usage_from_before_midnight_is_deleted_on_the_next_request(fake_llm):
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    kept, old = (
        UsageLog.objects.create(
            kind=UsageLog.Kind.REQUEST, path="llm", success=True, withdrawn_key=k
        )
        for k in ("a" * 64, "b" * 64)
    )
    UsageLog.objects.filter(pk=old.pk).update(created_at=midnight - timedelta(minutes=1))
    fake_llm.response = {"translation_ko": "학생입니다"}

    analyze(connected_client("someone"), "私は学生です。")

    assert UsageLog.objects.filter(pk=kept.pk).exists()
    assert not UsageLog.objects.filter(pk=old.pk).exists()


def admin_delete_one(admin_client, user):
    return admin_client.post(f"/admin/accounts/user/{user.pk}/delete/", {"post": "yes"})


def admin_delete_selected(admin_client, user):
    return admin_client.post(
        "/admin/accounts/user/",
        {"action": "delete_selected", "_selected_action": [user.pk], "post": "yes"},
    )


@pytest.mark.parametrize("delete", [admin_delete_one, admin_delete_selected])
def test_admin_deletion_withdraws_like_the_web(
    admin_client, delete, fake_llm, monkeypatch, settings
):
    # 정지된 계정은 이메일로 탈퇴를 요청하고 관리자가 지운다(#249). 화면 탈퇴와 결과가 같아야 한다.
    me, _ = user_with_records("me", fake_llm)
    User.objects.filter(pk=me.pk).update(google_sub="google-sub-1")
    me.refresh_from_db()
    other, _ = user_with_records("other", fake_llm)
    others = records_of(other)
    used = limits.today_tokens(me)

    response = delete(admin_client, me)

    assert response.status_code == 302
    assert not User.objects.filter(pk=me.pk).exists()
    assert not UserSentence.objects.filter(original_text__startswith="me").exists()
    assert not DesignatedName.objects.exclude(user=other).exists()
    assert not ExtensionToken.objects.exclude(user=other).exists()
    assert not UsageLog.objects.filter(user__isnull=True, withdrawn_key__isnull=True).exists()
    assert records_of(other) == others
    web = Client()
    assert limits.today_tokens(google_login(web, monkeypatch, settings, "google-sub-1")) == used


def test_purge_command_deletes_only_withdrawn_usage_from_before_midnight():
    # 분석 요청이 없는 날에도 늦어도 다음 날 지우도록 매일 예약 실행한다(#252).
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    kept, old, ordinary = (
        UsageLog.objects.create(
            kind=UsageLog.Kind.REQUEST, path="llm", success=True, withdrawn_key=k
        )
        for k in ("a" * 64, "b" * 64, None)
    )
    UsageLog.objects.filter(pk__in=[old.pk, ordinary.pk]).update(
        created_at=midnight - timedelta(minutes=1)
    )

    call_command("purge_withdrawn_usage")

    assert set(UsageLog.objects.values_list("pk", flat=True)) == {kept.pk, ordinary.pk}


def test_request_record_started_after_withdrawal_keeps_only_tokens_and_time(fake_llm):
    # 인증을 마친 요청이 처리 경로를 정하기 직전에 탈퇴가 커밋된 경우(PR #259 리뷰).
    me = User.objects.create(username="me", email="me@example.com", google_sub="google-sub-1")
    fake_llm.response = {"translation_ko": "학생입니다"}
    analyze(connected_client("someone"), "私は学生です。")
    analysis = SentenceAnalysis.objects.get()
    User.objects.filter(pk=me.pk).delete()

    usage.RequestUsage.start(UsageLog.Path.LLM, me, analysis.pk)

    row = carried_rows().get()
    assert row.user_id is None
    assert row.analysis_id is None
