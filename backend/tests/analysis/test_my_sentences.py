"""내 기록: 분석한 문장 목록, 저장된 분석 보기(#195), 문장별 삭제(#196). 웹 세션으로 본인 기록만
다룬다.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from analysis.models import SentenceAnalysis, UserSentence
from tests.accounts.test_withdrawal import web_session
from tests.analysis.helpers import analyze, connected_client, new_pattern

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


# 토큰: 0 私 / 1 は / 2 3 / 3 人 / 4 で / 5 走っ / 6 て / 7 いる
GRAMMAR_SENTENCE = "私は3人で走っている。"
GRAMMAR_RESPONSE = {
    "translation_ko": "나는 ⟨N1⟩명이서 달리고 있다.",
    "new_patterns": [
        new_pattern(
            (3, "lemma"),
            (4, "lemma"),
            pattern_name="人で",
            usage_name="인원",
            explanation_ko="함께하는 사람 수를 나타낸다",
            example_ja="5人で来た",
        ),
        new_pattern((6, "lemma"), (7, "lemma")),
    ],
}


def test_detail_shows_the_saved_analysis_without_llm(fake_llm):
    extension = connected_client("me")
    fake_llm.response = GRAMMAR_RESPONSE
    analyze(extension, GRAMMAR_SENTENCE)
    me = User.objects.get(username="me")
    target = row(me, GRAMMAR_SENTENCE)
    # 확장이 같은 문장을 다시 받을 때(캐시)의 결과와 같아야 한다.
    cached = analyze(extension, GRAMMAR_SENTENCE).json()
    fake_llm.forget_requests()
    web, _ = web_session(me)

    response = web.get(f"{LIST}{target.pk}/")

    assert response.status_code == 200
    body = response.json()
    assert fake_llm.all_requests() == []
    assert body == {
        "id": target.pk,
        "text": GRAMMAR_SENTENCE,
        "analyzed_at": body["analyzed_at"],
        "translation_ko": "나는 3명이서 달리고 있다.",
        "ruby": cached["ruby"],
        "grammar": cached["grammar"],
        "words": cached["words"],
        "name_spans": cached["name_spans"],
    }
    # LLM이 만든 패턴이라 미검수다.
    assert [(g["pattern_name"], g["review_status"]) for g in body["grammar"]] == [
        ("人で", "pending"),
        ("ている", "pending"),
    ]


def test_cannot_see_another_users_sentence(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。")
    other = analyzed("other", fake_llm, "他人の文です。")
    theirs = row(other, "他人の文です。")
    web, _ = web_session(me)

    response = web.get(f"{LIST}{theirs.pk}/")

    # 없는 기록과 같은 응답이라 남의 기록이 있는지 알 수 없다.
    assert (response.status_code, response.json()) == (404, {"error": "SENTENCE:NOT_FOUND"})
    assert web.get(f"{LIST}{theirs.pk + 1000}/").json() == {"error": "SENTENCE:NOT_FOUND"}


def test_detail_needs_a_logged_in_web_session(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。")
    target = row(me, "私は学生です。")
    extension = connected_client("me")

    for client in (Client(), extension):
        response = client.get(f"{LIST}{target.pk}/")
        assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_detail_of_a_record_pointing_to_another_key_is_outdated(fake_llm):
    me = analyzed("me", fake_llm, "私は学生です。", "猫が好きです。")
    target = row(me, "私は学生です。")
    # 정규화 규칙이 바뀌어 재연결하기 전이면 기록이 다른 키의 분석을 가리킬 수 있다.
    target.analysis = row(me, "猫が好きです。").analysis
    target.save()
    web, _ = web_session(me)

    response = web.get(f"{LIST}{target.pk}/")

    assert (response.status_code, response.json()) == (409, {"error": "SENTENCE:OUTDATED"})
