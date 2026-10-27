"""회원 탈퇴: 웹 세션으로 본인 계정과 개인 기록을 지운다(#239)."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from accounts import google
from accounts.models import ExtensionToken
from analysis import jobs
from analysis.models import DesignatedName, SentenceAnalysis, UsageLog, UserSentence
from tests.analysis.helpers import analyze, connected_client

pytestmark = pytest.mark.django_db

User = get_user_model()
WITHDRAW = "/api/auth/withdraw/"


def web_session(user):
    """그 사용자로 로그인한 웹 브라우저(CSRF 검사함)와 그 CSRF 헤더"""
    web = Client(enforce_csrf_checks=True)
    web.force_login(user)
    web.get("/api/auth/me/")
    return web, {"HTTP_X_CSRFTOKEN": web.cookies["csrftoken"].value}


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

    response = web.post(WITHDRAW, **headers)

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

    web.post(WITHDRAW, **headers)

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
    web.post(WITHDRAW, **headers)

    web.get("/api/auth/me/")
    response = web.post(
        "/api/auth/google/",
        {"credential": "google-id-token"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=web.cookies["csrftoken"].value,
    )

    assert response.json() == {"user": {"email": "me@example.com"}}
    again = User.objects.get(google_sub="google-sub-1")
    assert again.pk != me.pk
    assert not any(records_of(again).values())


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_withdrawal_during_an_analysis_leaves_no_record_behind(fake_llm):
    # 실제 커밋이 일어나야 외래키 검사가 돌므로 트랜잭션 테스트로 둔다.
    me = User.objects.create(username="me", email="me@example.com")
    extension = connected_client("me")
    web, headers = web_session(me)
    fake_llm.response = {"translation_ko": "학생입니다"}
    fake_llm.before_respond = lambda: web.post(WITHDRAW, **headers)

    analyze(extension, "私は学生です。")

    assert not User.objects.filter(pk=me.pk).exists()
    assert not UserSentence.objects.exists()
    assert not UsageLog.objects.filter(user_id=me.pk).exists()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_withdrawal_before_the_worker_starts_still_saves_the_shared_analysis(fake_llm, monkeypatch):
    # 같은 문장을 기다리는 다른 요청이 있을 수 있어 공용 분석은 끝까지 저장한다.
    me = User.objects.create(username="me", email="me@example.com")
    extension = connected_client("me")
    web, headers = web_session(me)
    fake_llm.response = {"translation_ko": "학생입니다"}
    enqueue = jobs.enqueue_analysis

    def withdraw_then_enqueue(*args):
        web.post(WITHDRAW, **headers)
        enqueue(*args)

    monkeypatch.setattr(jobs, "enqueue_analysis", withdraw_then_enqueue)

    analyze(extension, "私は学生です。")

    assert SentenceAnalysis.objects.get().status == SentenceAnalysis.Status.COMPLETE
    assert not UserSentence.objects.exists()
    assert not UsageLog.objects.exclude(user=None).exists()
