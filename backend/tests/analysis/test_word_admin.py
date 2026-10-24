"""관리 화면(Django admin)의 단어·뜻 검수(#97)."""

import pytest

from analysis.models import Word, WordSense
from tests.analysis.helpers import add_word

pytestmark = pytest.mark.django_db

WORDS = "/admin/analysis/word/"


@pytest.fixture
def gakusei():
    return add_word(3, ["学生"], ["がくせい"], [(["student"], [], None)])


@pytest.fixture
def taberu():
    """食べる: 뜻 둘. 하나는 AI 번역, 하나는 생성 실패."""
    word = add_word(
        5, ["食べる"], ["たべる"], [(["to eat"], ["transitive"], None), (["to live on"], [], None)]
    )
    word.senses.filter(jmdict_sense_index=1).update(
        meaning_ko="먹다", meaning_source="llm", meaning_status="ai"
    )
    word.senses.filter(jmdict_sense_index=2).update(meaning_status="failed")
    return word


@pytest.fixture
def made_up():
    """사전에 없는 단어(jmdict_seq 없음), 뜻은 검수됨."""
    word = add_word(None, ["推し"], ["おし"], [(["fave"], [], None)])
    word.senses.update(meaning_ko="최애", meaning_source="admin", meaning_status="reviewed")
    return word


def listed(page):
    return [str(word) for word in page.context["cl"].result_list]


@pytest.mark.parametrize(
    "query, found",
    [
        ("学生", ["学生【がくせい】"]),
        ("がくせい", ["学生【がくせい】"]),
        ("ガクセイ", ["学生【がくせい】"]),
    ],
)
def test_words_are_searched_by_form_or_reading(admin_client, gakusei, taberu, query, found):
    assert listed(admin_client.get(WORDS, {"q": query})) == found


@pytest.mark.parametrize(
    "value, found",
    [
        ("not_in_dictionary", ["推し【おし】"]),
        ("missing", ["学生【がくせい】"]),
        ("ai", ["食べる【たべる】"]),
        ("reviewed", ["推し【おし】"]),
        ("failed", ["食べる【たべる】"]),
    ],
)
def test_words_are_filtered_by_meaning_state(admin_client, gakusei, taberu, made_up, value, found):
    assert listed(admin_client.get(WORDS, {"meaning": value})) == found


def senses_form(word, meanings):
    """단어 변경 화면의 POST. meanings는 {뜻 번호: 한국어 뜻}으로 바꿀 뜻이다."""
    senses = list(word.senses.order_by("jmdict_sense_index"))
    data = {
        # JMdict 칸을 바꿔 보내도 읽기 전용이라 무시된다.
        "dictionary_form": "바뀜",
        "senses-TOTAL_FORMS": len(senses),
        "senses-INITIAL_FORMS": len(senses),
        "senses-MIN_NUM_FORMS": 0,
        "senses-MAX_NUM_FORMS": 1000,
    }
    for i, sense in enumerate(senses):
        data[f"senses-{i}-id"] = sense.pk
        data[f"senses-{i}-word"] = word.pk
        data[f"senses-{i}-meaning_ko"] = meanings.get(
            sense.jmdict_sense_index, sense.meaning_ko or ""
        )
        data[f"senses-{i}-gloss_en"] = '["바뀜"]'
    return data


def test_edited_meaning_becomes_reviewed_by_admin(admin_client, taberu):
    page = admin_client.get(f"{WORDS}{taberu.pk}/change/")
    assert "to live on" in page.content.decode()

    response = admin_client.post(f"{WORDS}{taberu.pk}/change/", senses_form(taberu, {2: "살다"}))

    assert response.status_code == 302
    eat, live = taberu.senses.order_by("jmdict_sense_index")
    assert (live.meaning_ko, live.meaning_source, live.meaning_status) == (
        "살다",
        "admin",
        "reviewed",
    )
    assert live.gloss_en == ["to live on"]
    # 고치지 않은 뜻은 그대로다.
    assert (eat.meaning_ko, eat.meaning_source, eat.meaning_status) == ("먹다", "llm", "ai")
    assert Word.objects.get(pk=taberu.pk).dictionary_form == "食べる"


def test_meaning_cannot_be_emptied(admin_client, taberu):
    response = admin_client.post(f"{WORDS}{taberu.pk}/change/", senses_form(taberu, {1: " "}))

    assert response.status_code == 200
    assert taberu.senses.get(jmdict_sense_index=1).meaning_ko == "먹다"


def run_action(admin_client, action, *words):
    return admin_client.post(
        WORDS, {"action": action, "_selected_action": [word.pk for word in words]}
    )


def test_review_actions_change_only_senses_with_a_meaning(admin_client, taberu):
    run_action(admin_client, "mark_reviewed", taberu)

    statuses = list(taberu.senses.order_by("jmdict_sense_index").values_list("meaning_status"))
    assert statuses == [("reviewed",), ("failed",)]

    run_action(admin_client, "unmark_reviewed", taberu)

    statuses = list(taberu.senses.order_by("jmdict_sense_index").values_list("meaning_status"))
    assert statuses == [("ai",), ("failed",)]


def test_words_and_senses_cannot_be_added_or_deleted(admin_client, gakusei):
    assert admin_client.get(f"{WORDS}add/").status_code == 403
    assert admin_client.get(f"{WORDS}{gakusei.pk}/delete/").status_code == 403
    assert "delete_selected" not in admin_client.get(WORDS).content.decode()
    assert WordSense.objects.count() == 1
