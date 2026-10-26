"""사용자가 표기를 이름으로 지정하기(#136). 지정한 이름은 본인만 쓰는 개인 데이터다."""

import pytest
from django.contrib import admin
from django.test import Client

from analysis import names as names_api
from analysis.models import DesignatedName, SentenceAnalysis, UsageLog, Word, WordSense
from tests.analysis.helpers import analyze, connected_client

pytestmark = pytest.mark.django_db


def put(client, surface, reading=""):
    return client.put(
        "/api/names/", {"surface": surface, "reading": reading}, content_type="application/json"
    )


def delete(client, surface):
    return client.delete("/api/names/", {"surface": surface}, content_type="application/json")


def names(client):
    return client.get("/api/names/").json()["names"]


def test_designated_name_is_saved_only_in_the_users_own_table(client, analyst, fake_llm):
    fake_llm.response = {"translation_ko": "봄이 왔다"}
    analyze(client, "春が来た")
    before = {
        model: list(model.objects.values())
        for model in (SentenceAnalysis, Word, WordSense, UsageLog)
    }

    response = put(client, "春", "はる")

    assert response.status_code == 200
    assert response.json() == {"surface": "春", "reading": "はる"}
    assert list(DesignatedName.objects.values_list("user", "surface", "reading")) == [
        (analyst.pk, "春", "はる")
    ]
    # 공용 테이블과 사용 기록은 그대로다.
    for model, rows in before.items():
        assert list(model.objects.values()) == rows
    assert names(client) == [{"surface": "春", "reading": "はる"}]


def test_saving_the_same_surface_again_only_changes_the_reading(client):
    put(client, "春", "はる")

    put(client, "春", "しゅん")

    assert names(client) == [{"surface": "春", "reading": "しゅん"}]
    assert DesignatedName.objects.count() == 1


@pytest.mark.parametrize(
    ("reading", "stored"),
    [
        ("ハル", "はる"),
        ("", None),
        (None, None),
        ("はーる", "はーる"),
        ("コーヒー", "こーひー"),
        ("さゝき", "さゝき"),
    ],
)
def test_reading_is_stored_in_hiragana_or_null(client, reading, stored):
    put(client, "春", reading)

    assert DesignatedName.objects.get().reading == stored


@pytest.mark.parametrize(
    ("surface", "reading"),
    [
        ("春", "haru"),
        ("春", "春"),
        ("春", "は" * 51),
        ("春" * 51, "はる"),
        ("", "はる"),
        (None, "はる"),
        ("  ", "はる"),
    ],
)
def test_invalid_surface_or_reading_is_refused(client, surface, reading):
    response = put(client, surface, reading)

    assert response.status_code == 400
    assert response.json()["error"] == "NAME:INVALID"
    assert not DesignatedName.objects.exists()


@pytest.mark.parametrize("reading", ["ー", "ゝ", "ヽ"])
def test_reading_without_kana_does_not_replace_a_designated_name(client, reading):
    put(client, "春", "はる")

    response = put(client, "春", reading)

    assert response.status_code == 400
    assert response.json()["error"] == "NAME:INVALID"
    assert names(client) == [{"surface": "春", "reading": "はる"}]


def test_refusal_does_not_echo_the_surface(client, caplog):
    response = put(client, "秘密の名前", "haru")

    assert "秘密の名前" not in response.content.decode()
    assert "秘密の名前" not in caplog.text


def test_body_that_is_not_an_object_is_refused(client):
    response = client.put("/api/names/", ["春"], content_type="application/json")

    assert response.json()["error"] == "NAME:INVALID"


def test_other_users_cannot_see_change_or_remove_the_name(client):
    put(client, "春", "はる")
    other = connected_client("other")

    assert names(other) == []
    # 같은 표기를 지정해도 자기 행만 생기고, 지워도 자기 행만 지워진다.
    put(other, "春", "しゅん")
    assert names(client) == [{"surface": "春", "reading": "はる"}]
    delete(other, "春")
    assert names(other) == []
    assert names(client) == [{"surface": "春", "reading": "はる"}]


def test_other_users_analysis_of_the_same_sentence_is_unchanged(client, fake_llm):
    fake_llm.response = {"translation_ko": "봄이 왔다"}
    other = connected_client("other")
    first = analyze(other, "春が来た").events

    put(client, "春", "はる")

    assert analyze(other, "春が来た").events == first


def test_removing_a_name_deletes_the_row(client):
    put(client, "春", "はる")

    response = delete(client, "春")

    assert response.status_code == 204
    assert not DesignatedName.objects.exists()
    # 지정하지 않은 표기를 지워도 오류가 아니다.
    assert delete(client, "夏").status_code == 204


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_requests_without_login_are_refused(method):
    response = getattr(Client(), method)("/api/names/", {}, content_type="application/json")

    assert response.status_code == 401
    assert response.json()["error"] == "AUTH:LOGIN_REQUIRED"


def test_names_are_deleted_with_the_user(client, analyst):
    put(client, "春", "はる")

    analyst.delete()

    assert not DesignatedName.objects.exists()


def test_designated_name_is_not_in_django_admin():
    assert not admin.site.is_registered(DesignatedName)


def test_new_names_beyond_the_per_user_limit_are_refused(client, analyst, monkeypatch):
    monkeypatch.setattr(names_api, "MAX_NAMES", 2)
    put(client, "春", "はる")
    put(client, "夏", "なつ")

    response = put(client, "秋", "あき")

    assert response.status_code == 409
    assert response.json()["error"] == "NAME:TOO_MANY"
    assert DesignatedName.objects.count() == 2
    # 이미 지정한 표기의 읽기 고치기와 다른 사용자의 지정은 막지 않는다.
    assert put(client, "春", "しゅん").status_code == 200
    assert put(connected_client("other"), "秋", "あき").status_code == 200
