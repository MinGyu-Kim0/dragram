"""내 기록: 분석한 문장 목록과 문장별 삭제(#196). 웹 세션으로 본인 기록만 다룬다."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from analysis.models import SentenceAnalysis, UserSentence
from tests.accounts.test_withdrawal import web_session
from tests.analysis.helpers import analyze, connected_client

pytestmark = pytest.mark.django_db

User = get_user_model()
LIST = "/api/my-sentences/"


def analyzed(username, fake_llm, *texts):
    """확장으로 문장들을 분석한 사용자"""
    client = connected_client(username)
    fake_llm.response = {"translation_ko": "번역"}
    for text in texts:
        analyze(client, text)
    return User.objects.get(username=username)


def row(user, text):
    return UserSentence.objects.get(user=user, original_text=text)


def delete(web, headers, sentence_id):
    return web.delete(f"{LIST}{sentence_id}/", **headers)


def test_list_shows_only_my_sentences_most_recent_first(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。", "猫が好きです。")
    analyzed("other", fake_llm, "他人の文です。")
    older = row(me, "私は学生です。")
    older.last_analyzed_at = timezone.now() - timedelta(days=1)
    older.save()
    web, _ = web_session(me)

    response = web.get(LIST)

    assert response.status_code == 200
    sentences = response.json()["sentences"]
    assert [s["text"] for s in sentences] == ["猫が好きです。", "私は学生です。"]
    assert sentences[1] == {
        "id": older.pk,
        "text": "私は学生です。",
        "analyzed_at": older.last_analyzed_at.isoformat().replace("+00:00", "Z"),
    }


def test_list_needs_a_logged_in_web_session(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。")
    extension = connected_client("me2")

    for client in (Client(), extension):
        response = client.get(LIST)
        assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})
    assert UserSentence.objects.filter(user=me).exists()


def test_delete_removes_only_that_original_and_keeps_the_shared_analysis(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。", "猫が好きです。")
    target = row(me, "私は学生です。")
    analyses = SentenceAnalysis.objects.count()
    web, headers = web_session(me)

    response = delete(web, headers, target.pk)

    assert response.status_code == 204
    assert not UserSentence.objects.filter(pk=target.pk).exists()
    assert SentenceAnalysis.objects.filter(pk=target.analysis_id).exists()
    assert SentenceAnalysis.objects.count() == analyses
    assert [s["text"] for s in web.get(LIST).json()["sentences"]] == ["猫が好きです。"]


def test_cannot_delete_another_users_sentence(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。")
    other = analyzed("other", fake_llm, "他人の文です。")
    theirs = row(other, "他人の文です。")
    web, headers = web_session(me)

    response = delete(web, headers, theirs.pk)

    # 없는 기록과 같은 응답이라 남의 기록이 있는지 알 수 없다.
    assert (response.status_code, response.json()) == (404, {"error": "SENTENCE:NOT_FOUND"})
    assert delete(web, headers, theirs.pk + 1000).json() == {"error": "SENTENCE:NOT_FOUND"}
    assert UserSentence.objects.filter(pk=theirs.pk).exists()


def test_delete_without_csrf_or_login_is_refused(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。")
    target = row(me, "私は学生です。")
    web, _ = web_session(me)
    anonymous = Client(enforce_csrf_checks=True)
    anonymous.get("/api/auth/me/")

    no_csrf = delete(web, {}, target.pk)
    no_login = delete(
        anonymous, {"HTTP_X_CSRFTOKEN": anonymous.cookies["csrftoken"].value}, target.pk
    )

    assert (no_csrf.status_code, no_csrf.json()) == (403, {"error": "AUTH:CSRF_FAILED"})
    assert (no_login.status_code, no_login.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})
    assert UserSentence.objects.filter(pk=target.pk).exists()
