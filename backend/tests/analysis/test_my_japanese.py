"""내 일본어: 사용자가 추가하거나 숨긴 용법(#313)·단어 뜻(#314)을 웹에 보인다(#322, FR-M10).
웹 세션으로 본인 항목만 다루고 LLM을 부르지 않는다.
"""

import json
from unittest.mock import ANY

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from analysis.models import GrammarUsage, ReviewStatus, SpanMatch, WordSense
from tests.accounts.test_withdrawal import web_session
from tests.analysis.helpers import add_word, analyze, connected_client, new_pattern

pytestmark = pytest.mark.django_db

User = get_user_model()
GRAMMAR = "/api/my-japanese/grammar/"
WORDS = "/api/my-japanese/words/"

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


@pytest.fixture
def usages(fake_llm):
    """분석으로 생긴 용법 (人で 인원, ている 진행)"""
    fake_llm.response = GRAMMAR_RESPONSE
    analyze(connected_client("seed"), GRAMMAR_SENTENCE)
    fake_llm.forget_requests()
    return [SpanMatch.objects.get(pattern__name=name).usage for name in ("人で", "ている")]


def put(client, kind, target, state, example=None, mark=None):
    """example을 주면 그 안의 mark 부분을 카드 구간으로 함께 보낸다."""
    body = {"kind": kind, "id": target.pk, "state": state}
    if example is not None:
        start = example.index(mark)
        body |= {"example": example, "example_start": start, "example_end": start + len(mark)}
    response = client.put("/api/my-items/", json.dumps(body), content_type="application/json")
    assert response.status_code == 200


def listed(user, url, state=None):
    web, _ = web_session(user)
    response = web.get(url, {"state": state} if state else {})
    assert response.status_code == 200
    return response.json()


def test_grammar_lists_added_usages_with_examples_most_recent_first(usages, fake_llm):
    人で, ている = usages
    extension = connected_client("me")
    put(extension, "usage", ている, "added", "雨が降っている。", "ている")
    put(extension, "usage", 人で, "added")
    put(extension, "usage", ている, "added", "猫が寝ている。", "ている")
    put(connected_client("other"), "usage", 人で, "hidden")
    me = User.objects.get(username="me")

    usages_listed = listed(me, GRAMMAR)["usages"]

    assert fake_llm.all_requests() == []
    assert [u["pattern_name"] for u in usages_listed] == ["ている", "人で"]
    examples = usages_listed[0]["examples"]
    assert usages_listed[0] == {
        "usage_id": ている.pk,
        "pattern_name": "ている",
        "name": "진행",
        "explanation_ko": "동작이 이어지고 있음을 나타낸다",
        "korean_equivalent": None,
        "korean_equivalent_review_status": None,
        "review_status": "pending",
        "examples": [
            {"id": examples[0]["id"], "text": "雨が降っている。", "start": 4, "end": 7},
            {"id": examples[1]["id"], "text": "猫が寝ている。", "start": 3, "end": 6},
        ],
    }
    assert usages_listed[1]["examples"] == []


def test_hidden_filter_lists_only_hidden_items(usages):
    人で, ている = usages
    extension = connected_client("me")
    put(extension, "usage", 人で, "hidden")
    put(extension, "usage", ている, "added")
    me = User.objects.get(username="me")

    assert [u["name"] for u in listed(me, GRAMMAR, "hidden")["usages"]] == ["인원"]
    assert [u["name"] for u in listed(me, GRAMMAR)["usages"]] == ["진행"]


def test_rejected_usage_shows_only_its_examples_and_approved_has_no_pending_badge(usages):
    人で, ている = usages
    extension = connected_client("me")
    put(extension, "usage", 人で, "added", "5人で来た。", "人で")
    put(extension, "usage", ている, "added")
    GrammarUsage.objects.filter(pk=人で.pk).update(status=ReviewStatus.REJECTED)
    GrammarUsage.objects.filter(pk=ている.pk).update(status=ReviewStatus.APPROVED)
    ている.pattern.status = ReviewStatus.APPROVED
    ている.pattern.save()

    usages_listed = listed(User.objects.get(username="me"), GRAMMAR)["usages"]

    # 반려된 용법은 내용 없이 예문만 보내, 사용자가 자기 원문을 지울 수 있게 한다.
    approved, rejected = usages_listed
    assert rejected == {
        "usage_id": 人で.pk,
        "rejected": True,
        "examples": [{"id": ANY, "text": "5人で来た。", "start": 1, "end": 3}],
    }
    assert (approved["name"], approved["review_status"]) == ("진행", "approved")


def test_words_lists_added_senses_with_dictionary_fields(fake_llm):
    run = add_word(1, ["走る"], ["はしる"], [(["to run"], ["v5r"], None)], tags=("verb", "group1"))
    sense = run.senses.get()
    sense.meaning_ko = "달리다"
    sense.save()
    rejected = add_word(2, ["私"], ["わたし"], [(["I"], [], None)]).senses.get()
    extension = connected_client("me")
    put(extension, "sense", sense, "added", "毎朝走る。", "走る")
    put(extension, "sense", rejected, "added")
    WordSense.objects.filter(pk=rejected.pk).update(sense_status=ReviewStatus.REJECTED)

    words = listed(User.objects.get(username="me"), WORDS)["words"]

    assert words.pop(0) == {"sense_id": rejected.pk, "rejected": True, "examples": []}
    assert words == [
        {
            "sense_id": sense.pk,
            "dictionary_form": "走る",
            "reading": "はしる",
            "tags": ["group1", "verb"],
            "in_dictionary": True,
            "sense": {
                "id": ANY,
                "tags": ["v5r"],
                "gloss_en": ["to run"],
                "origin": "jmdict",
                "status": "approved",
                "meaning_ko": "달리다",
                "meaning_status": "ai",
            },
            "examples": [{"id": words[0]["examples"][0]["id"], "text": "毎朝走る。", "start": 2, "end": 4}],
        }
    ]


@pytest.mark.parametrize("url", [GRAMMAR, WORDS])
def test_needs_a_logged_in_web_session_and_a_known_state(url):
    for client in (Client(), connected_client("me2")):
        response = client.get(url)
        assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})
    web, _ = web_session(User.objects.create(username="me"))
    response = web.get(url, {"state": "all"})
    assert (response.status_code, response.json()) == (400, {"error": "MY_ITEM:INVALID"})
