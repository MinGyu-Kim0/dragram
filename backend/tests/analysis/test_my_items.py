"""내 일본어 항목(#322): 사용자가 사이드 패널 카드에서 추가하거나 숨긴 용법·단어 뜻과, 추가할 때
고른 예문. 확장(Bearer)과 웹(세션) 모두 본인 것만 다룬다. 예문 원문은 이 기록에만 둔다.
"""

import json

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import serializers
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
# 예문에서 그 카드가 가리키는 부분(ていた). 원문 기준 UTF-16 위치다.
WITH_EXAMPLE = {"example": EXAMPLE, "example_start": 11, "example_end": 14}


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


def item(kind, target, added, hidden, **extra):
    """API가 돌려주는 항목. state는 옛 확장을 위한 칸이다(#362)."""
    state = "hidden" if hidden else "added"
    return {
        "kind": kind,
        "id": target.pk,
        "added": added,
        "hidden": hidden,
        "state": state,
        **extra,
    }


def test_add_exclude_hide_and_restore_are_separate_axes(usage, sense):
    """추가·제외는 내 일본어, 숨김·복원은 사이드 패널 표시다. 둘 다 꺼지면 항목이 사라진다(#362)."""
    extension = connected_client("me")

    added = send(extension, "put", {"kind": "usage", "id": usage.pk, "added": True})
    hidden = send(extension, "put", {"kind": "sense", "id": sense.pk, "hidden": True})

    assert added.status_code == 200
    assert added.json() == item("usage", usage, True, False)
    assert hidden.json() == item("sense", sense, False, True)
    assert states(extension) == [
        item("usage", usage, True, False, has_examples=False),
        item("sense", sense, False, True, has_examples=False),
    ]
    # 추가한 항목을 숨겨도 추가는 그대로고, 복원하면 숨김만 풀린다.
    hide = send(extension, "put", {"kind": "usage", "id": usage.pk, "hidden": True})
    assert hide.json() == item("usage", usage, True, True)
    assert MyItem.objects.filter(usage=usage).count() == 1
    restore = send(extension, "put", {"kind": "usage", "id": usage.pk, "hidden": False})
    assert restore.json() == item("usage", usage, True, False)
    # 제외하면 추가가 꺼지고, 숨기지도 않았으니 항목이 사라진다.
    exclude = send(extension, "put", {"kind": "usage", "id": usage.pk, "added": False})
    assert exclude.json() == {
        "kind": "usage",
        "id": usage.pk,
        "added": False,
        "hidden": False,
        "state": None,
    }
    # 추가하지 않고 숨긴 항목을 복원해도 사라진다.
    send(extension, "put", {"kind": "sense", "id": sense.pk, "hidden": False})
    assert states(extension) == []


def test_delete_still_clears_both_axes(usage):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "added": True, "hidden": True})

    assert send(extension, "delete", {"kind": "usage", "id": usage.pk}).status_code == 204
    assert states(extension) == []


def test_hiding_and_restoring_keep_examples_and_excluding_deletes_them(usage):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "added": True, **WITH_EXAMPLE})

    send(extension, "put", {"kind": "usage", "id": usage.pk, "hidden": True})
    send(extension, "put", {"kind": "usage", "id": usage.pk, "hidden": False})
    assert MyExample.objects.count() == 1

    # 숨긴 채 제외하면 예문은 지우고 숨김은 남긴다.
    send(extension, "put", {"kind": "usage", "id": usage.pk, "hidden": True})
    excluded = send(extension, "put", {"kind": "usage", "id": usage.pk, "added": False})
    assert excluded.json() == item("usage", usage, False, True)
    assert not MyExample.objects.exists()


def test_old_extension_state_requests_still_work(usage, sense):
    """스토어에 배포된 옛 확장은 state만 보낸다(#362 호환)."""
    extension = connected_client("me")

    added = send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added"})
    assert added.json() == item("usage", usage, True, False)
    # 옛 숨김은 추가 여부를 건드리지 않는다.
    hidden = send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "hidden"})
    assert hidden.json() == item("usage", usage, True, True)
    send(extension, "put", {"kind": "sense", "id": sense.pk, "state": "hidden"})
    # 옛 추가는 숨김도 푼다(옛 확장에서 숨긴 카드는 추가 버튼이 없어 다시 보이기로만 돌아왔다).
    again = send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added"})
    assert again.json() == item("usage", usage, True, False)
    assert states(extension) == [
        item("usage", usage, True, False, has_examples=False),
        item("sense", sense, False, True, has_examples=False),
    ]


def test_adding_with_an_example_keeps_only_that_sentence(usage):
    extension = connected_client("me")

    for _ in range(2):
        response = send(
            extension,
            "put",
            {"kind": "usage", "id": usage.pk, "added": True, **WITH_EXAMPLE},
        )
        assert response.status_code == 200

    example = MyExample.objects.get()
    assert (example.item.usage, example.original_text) == (usage, EXAMPLE)
    assert (example.highlight_start, example.highlight_end) == (11, 14)
    # 예문 없이 다시 추가해도 저장한 예문은 그대로다.
    send(extension, "put", {"kind": "usage", "id": usage.pk, "added": True})
    assert MyExample.objects.count() == 1


def test_item_list_tells_which_items_have_examples(usage, sense):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "added": True, **WITH_EXAMPLE})
    send(extension, "put", {"kind": "usage", "id": usage.pk, "hidden": True})
    send(extension, "put", {"kind": "sense", "id": sense.pk, "hidden": True})

    # 확장이 제외하기 전에 예문이 함께 지워짐을 확인받을 수 있게 알린다(PR #320 리뷰).
    assert extension.get(ITEMS).json()["items"] == [
        item("usage", usage, True, True, has_examples=True),
        item("sense", sense, False, True, has_examples=False),
    ]


@pytest.mark.parametrize(
    "change",
    [{"state": "hidden"}, {"hidden": True}, {"added": False}, {"added": True, "hidden": True}],
)
def test_only_adding_takes_an_example(usage, change):
    response = send(
        connected_client("me"),
        "put",
        {"kind": "usage", "id": usage.pk, **change, **WITH_EXAMPLE},
    )

    assert (response.status_code, response.json()) == (400, {"error": "MY_ITEM:INVALID"})
    assert not MyItem.objects.exists()


def test_removing_an_item_deletes_its_examples(usage):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "added": True, **WITH_EXAMPLE})

    send(extension, "delete", {"kind": "usage", "id": usage.pk})

    assert not MyExample.objects.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "pattern", "id": 1, "state": "added"},
        {"kind": ["usage"], "id": 1, "state": "added"},
        {"kind": {"usage": 1}, "id": 1, "state": "added"},
        {"kind": "usage", "id": "1", "state": "added"},
        {"kind": "usage", "id": 999999, "state": "added"},
        {"kind": "usage", "id": None, "state": "added"},
        {"kind": "usage", "state": "shown"},
        {"kind": "usage", "state": "added", "example": ""},
        {"kind": "usage", "state": "added", "example": "あ" * 1001},
        {"kind": "usage", "state": "added", "example": "A\x00B"},
        {"kind": "usage", "state": "added", "example": "\ud800"},
        {"kind": "usage", "state": "added", "example": EXAMPLE},
        {**WITH_EXAMPLE, "kind": "usage", "state": "added", "example_start": "11"},
        {**WITH_EXAMPLE, "kind": "usage", "state": "added", "example_start": True},
        {**WITH_EXAMPLE, "kind": "usage", "state": "added", "example_start": -1},
        {**WITH_EXAMPLE, "kind": "usage", "state": "added", "example_start": 14},
        {**WITH_EXAMPLE, "kind": "usage", "state": "added", "example_end": 16},
        {"kind": "usage", "state": "added", "example_start": 0, "example_end": 1},
        {"kind": "usage"},
        {"kind": "usage", "added": 1},
        {"kind": "usage", "hidden": "true"},
        {"kind": "usage", "added": None},
        {"kind": "usage", "state": "added", "added": True},
        ["usage"],
    ],
)
def test_invalid_requests_are_refused_without_changes(usage, body):
    if isinstance(body, dict) and "id" not in body:
        body = {**body, "id": usage.pk}

    response = send(connected_client("me"), "put", body)

    assert (response.status_code, response.json()) == (400, {"error": "MY_ITEM:INVALID"})
    assert not MyItem.objects.exists()


@pytest.mark.parametrize("rejected", ["usage", "pattern"])
def test_rejected_usage_cannot_be_added_but_can_be_removed_with_its_examples(usage, rejected):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added", **WITH_EXAMPLE})
    target = usage if rejected == "usage" else usage.pattern
    target.status = ReviewStatus.REJECTED
    target.save()

    again = send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "hidden"})
    removed = send(extension, "delete", {"kind": "usage", "id": usage.pk})

    assert (again.status_code, again.json()) == (400, {"error": "MY_ITEM:INVALID"})
    assert removed.status_code == 204
    assert not MyExample.objects.exists()


def test_each_user_sees_and_changes_only_own_items(usage):
    mine, theirs = connected_client("me"), connected_client("other")
    send(theirs, "put", {"kind": "usage", "id": usage.pk, "state": "added", **WITH_EXAMPLE})

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
    assert states(web) == [item("usage", usage, True, False, has_examples=False)]


def test_needs_login(usage):
    for method in ("get", "put", "delete"):
        response = send(Client(), method, {"kind": "usage", "id": usage.pk, "state": "added"})
        assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_items_and_examples_go_with_the_user(usage):
    extension = connected_client("me")
    send(extension, "put", {"kind": "usage", "id": usage.pk, "state": "added", **WITH_EXAMPLE})

    User.objects.get(username="me").delete()

    assert not MyItem.objects.exists()
    assert not MyExample.objects.exists()


def test_example_delete_removes_only_my_example(usage):
    mine, theirs = connected_client("me"), connected_client("other")
    for client in (mine, theirs):
        send(client, "put", {"kind": "usage", "id": usage.pk, "state": "added", **WITH_EXAMPLE})
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
    send(extension, "put", {"kind": "usage", "id": usage.pk, "added": True, **WITH_EXAMPLE})
    send(extension, "put", {"kind": "usage", "id": target.pk, "hidden": True})

    with transaction.atomic():
        merge_usage(usage, target)

    # 어느 쪽이라도 추가면 추가이고, 숨김은 양쪽 모두 숨겼을 때만이다. 예문은 합친 항목으로 옮긴다.
    assert states(extension) == [item("usage", target, True, False, has_examples=True)]
    assert MyExample.objects.get().item.usage == target


def test_example_is_kept_only_in_my_example_and_not_logged(usage, caplog):
    send(
        connected_client("me"),
        "put",
        {"kind": "usage", "id": usage.pk, "state": "added", **WITH_EXAMPLE},
    )

    assert EXAMPLE not in caplog.text
    for model in apps.get_models():
        if model is MyExample:
            continue
        assert EXAMPLE not in serializers.serialize("json", model.objects.all()), model
