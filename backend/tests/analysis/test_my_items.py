"""내 일본어 항목(#322): 사용자가 사이드 패널 카드에서 추가하거나 숨긴 용법·단어 뜻과, 추가할 때
고른 예문. 확장(Bearer)과 웹(세션) 모두 본인 것만 다룬다. 예문 원문은 이 기록에만 둔다.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client

from analysis.models import MyExample, MyItem, ReviewStatus, SpanMatch
from tests.accounts.test_withdrawal import web_session
from tests.analysis.helpers import add_word, analyze, connected_client
from tests.analysis.test_my_japanese import GRAMMAR_RESPONSE, GRAMMAR_SENTENCE

pytestmark = pytest.mark.django_db

User = get_user_model()
ITEMS = "/api/my-items/"
EXAMPLE = "その日、私は3人で走っていた。"


@pytest.fixture
def usage(fake_llm):
    """분석으로 생긴 용법(ている 진행)"""
    fake_llm.response = GRAMMAR_RESPONSE
    analyze(connected_client("seed"), GRAMMAR_SENTENCE)
    return SpanMatch.objects.get(pattern__name="ている").usage


@pytest.fixture
def sense():
    return add_word(1, ["走る"], ["はしる"], [(["to run"], [], None)]).senses.get()


def send(client, method, body, **headers):
    if method == "get":
        return client.get(ITEMS, **headers)
    return getattr(client, method)(
        ITEMS, data=json.dumps(body), content_type="application/json", **headers
    )


def states(client):
    response = client.get(ITEMS)
    assert response.status_code == 200
    return response.json()["items"]


def test_extension_adds_hides_and_removes_items(usage, sense):
    extension = connected_client("me")

    added = send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added"})
    hidden = send(extension, "put", {"kind": "sense", "id": sense.pk, "state": "hidden"})

    assert added.status_code == 200
    assert added.json() == {"kind": "usage", "id": usage.pk, "state": "added"}
    assert hidden.json() == {"kind": "sense", "id": sense.pk, "state": "hidden"}
    assert states(extension) == [
        {"kind": "usage", "id": usage.pk, "state": "added"},
        {"kind": "sense", "id": sense.pk, "state": "hidden"},
    ]
    # 같은 항목을 다시 보내면 상태만 바뀐다.
    send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "hidden"})
    assert MyItem.objects.filter(usage=usage).count() == 1
    assert send(extension, "delete", {"kind": "usage", "id": usage.pk}).status_code == 204
    assert states(extension) == [{"kind": "sense", "id": sense.pk, "state": "hidden"}]


def test_adding_with_an_example_keeps_only_that_sentence(usage):
    extension = connected_client("me")

    for _ in range(2):
        response = send(
            extension,
            "put",
            {"kind": "usage", "id": usage.pk, "state": "added", "example": EXAMPLE},
        )
        assert response.status_code == 200

    example = MyExample.objects.get()
    assert (example.item.usage, example.original_text) == (usage, EXAMPLE)
    # 예문 없이 다시 추가해도 저장한 예문은 그대로다.
    send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added"})
    assert MyExample.objects.count() == 1


def test_hiding_does_not_take_an_example(usage):
    response = send(
        connected_client("me"),
        "put",
        {"kind": "usage", "id": usage.pk, "state": "hidden", "example": EXAMPLE},
    )

    assert (response.status_code, response.json()) == (400, {"error": "MY_ITEM:INVALID"})
    assert not MyItem.objects.exists()


def test_removing_an_item_deletes_its_examples(usage):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added", "example": EXAMPLE})

    send(extension, "delete", {"kind": "usage", "id": usage.pk})

    assert not MyExample.objects.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "pattern", "id": 1, "state": "added"},
        {"kind": "usage", "id": "1", "state": "added"},
        {"kind": "usage", "id": 999999, "state": "added"},
        {"kind": "usage", "id": None, "state": "added"},
        {"kind": "usage", "state": "shown"},
        {"kind": "usage", "state": "added", "example": ""},
        {"kind": "usage", "state": "added", "example": "あ" * 1001},
        {"kind": "usage", "state": "added", "example": "A\x00B"},
        {"kind": "usage", "state": "added", "example": "\ud800"},
        ["usage"],
    ],
)
def test_invalid_requests_are_refused_without_changes(usage, body):
    if isinstance(body, dict) and "id" not in body:
        body = {**body, "id": usage.pk}

    response = send(connected_client("me"), "put", body)

    assert (response.status_code, response.json()) == (400, {"error": "MY_ITEM:INVALID"})
    assert not MyItem.objects.exists()


def test_rejected_usage_cannot_be_added(usage):
    usage.status = ReviewStatus.REJECTED
    usage.save()

    response = send(
        connected_client("me"), "put", {"kind": "usage", "id": usage.pk, "state": "added"}
    )

    assert (response.status_code, response.json()) == (400, {"error": "MY_ITEM:INVALID"})


def test_each_user_sees_and_changes_only_own_items(usage):
    mine, theirs = connected_client("me"), connected_client("other")
    send(theirs, "put", {"kind": "usage", "id": usage.pk, "state": "added", "example": EXAMPLE})

    assert states(mine) == []
    send(mine, "delete", {"kind": "usage", "id": usage.pk})
    assert MyItem.objects.filter(user__username="other").count() == 1
    assert MyExample.objects.count() == 1


def test_web_session_needs_csrf_to_change(usage):
    me = User.objects.create(username="me")
    web, headers = web_session(me)

    refused = send(web, "put", {"kind": "usage", "id": usage.pk, "state": "added"})
    accepted = send(web, "put", {"kind": "usage", "id": usage.pk, "state": "added"}, **headers)

    assert (refused.status_code, refused.json()) == (403, {"error": "AUTH:CSRF_FAILED"})
    assert accepted.status_code == 200
    assert states(web) == [{"kind": "usage", "id": usage.pk, "state": "added"}]


def test_needs_login(usage):
    for method in ("get", "put", "delete"):
        response = send(Client(), method, {"kind": "usage", "id": usage.pk, "state": "added"})
        assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_items_and_examples_go_with_the_user(usage):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added", "example": EXAMPLE})

    User.objects.get(username="me").delete()

    assert not MyItem.objects.exists()
    assert not MyExample.objects.exists()


def test_example_delete_removes_only_my_example(usage):
    mine, theirs = connected_client("me"), connected_client("other")
    for client in (mine, theirs):
        send(client, "put", {"kind": "usage", "id": usage.pk, "state": "added", "example": EXAMPLE})
    my_example = MyExample.objects.get(item__user__username="me")
    their_example = MyExample.objects.get(item__user__username="other")

    assert mine.delete(f"/api/my-examples/{their_example.pk}/").status_code == 404
    assert mine.delete(f"/api/my-examples/{my_example.pk}/").status_code == 204
    assert list(MyExample.objects.all()) == [their_example]


def test_merging_usages_keeps_the_users_item(usage):
    from analysis.models import GrammarUsage
    from analysis.patterns import merge_usage

    target = GrammarUsage.objects.create(
        pattern=usage.pattern,
        name="결과 상태",
        explanation_ko="동작의 결과가 남아 있음을 나타낸다",
        status=ReviewStatus.PENDING,
        origin=GrammarUsage.Origin.ADMIN,
    )
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added", "example": EXAMPLE})
    send(extension, "put", {"kind": "usage", "id": target.pk, "state": "hidden"})

    with transaction.atomic():
        merge_usage(usage, target)

    # 추가가 숨김보다 앞서고, 예문은 합친 항목으로 옮긴다.
    assert states(extension) == [{"kind": "usage", "id": target.pk, "state": "added"}]
    assert MyExample.objects.get().item.usage == target


def test_example_is_not_logged(usage, caplog):
    send(
        connected_client("me"),
        "put",
        {"kind": "usage", "id": usage.pk, "state": "added", "example": EXAMPLE},
    )

    assert EXAMPLE not in caplog.text
