"""관리 화면(Django admin)의 패턴·용법 검수(#38)."""

import html
import json

import pytest

from analysis.models import GrammarPattern, GrammarUsage, ReviewStatus
from tests.analysis.helpers import analyze, new_pattern

pytestmark = pytest.mark.django_db

ORIGINAL = "昨日図書館で本を読んでいる"
PATTERNS = "/admin/analysis/grammarpattern/"
USAGES = "/admin/analysis/grammarusage/"


@pytest.fixture
def pattern(client, fake_llm):
    # 토큰: 0 昨日 / 1 図書館 / 2 で / 3 本 / 4 を / 5 読ん / 6 で / 7 いる
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [new_pattern((6, "lemma"), (7, "lemma"))],
    }
    analyze(client, ORIGINAL)
    return GrammarPattern.objects.get()


@pytest.mark.parametrize("url", ["/admin/analysis/sentenceanalysis/", "/admin/analysis/spanmatch/"])
def test_tables_with_sentence_positions_are_not_in_admin(admin_client, pattern, url):
    assert admin_client.get(url).status_code == 404


def test_admin_pages_do_not_show_the_original_sentence(admin_client, pattern):
    usage = pattern.usages.get()
    pages = [
        admin_client.get(PATTERNS),
        admin_client.get(f"{PATTERNS}{pattern.pk}/change/"),
        admin_client.get(USAGES),
        admin_client.get(f"{USAGES}{usage.pk}/change/"),
    ]

    for page in pages:
        assert page.status_code == 200
        assert ORIGINAL not in page.content.decode()


def pattern_form(pattern, **changes):
    return {
        "name": pattern.name,
        "test_cases": json.dumps(pattern.test_cases, ensure_ascii=False),
        "morphemes-TOTAL_FORMS": "0",
        "morphemes-INITIAL_FORMS": "0",
        **changes,
    }


def test_pattern_name_and_test_cases_can_be_edited(admin_client, pattern):
    cases = [
        {"text": "雨が降っている", "should_match": True},
        {"text": "雨が降る", "should_match": False},
    ]

    response = admin_client.post(
        f"{PATTERNS}{pattern.pk}/change/",
        pattern_form(pattern, name="〜ている", test_cases=json.dumps(cases, ensure_ascii=False)),
    )

    assert response.status_code == 302
    pattern.refresh_from_db()
    assert (pattern.name, pattern.test_cases) == ("〜ている", cases)


@pytest.mark.parametrize(
    "cases",
    [
        {"text": "雨が降っている", "should_match": True},
        [{"text": "雨が降っている"}],
        [{"text": "雨が降っている", "should_match": "yes"}],
        [{"text": 1, "should_match": True}],
        [{"text": "雨が⟨N1⟩回降っている", "should_match": True}],
        [{"text": "あ" * 201, "should_match": False}],
    ],
)
def test_malformed_test_cases_are_not_saved(admin_client, pattern, cases):
    before = pattern.test_cases

    response = admin_client.post(
        f"{PATTERNS}{pattern.pk}/change/",
        pattern_form(pattern, test_cases=json.dumps(cases, ensure_ascii=False)),
    )

    assert response.status_code == 200
    pattern.refresh_from_db()
    assert pattern.test_cases == before


def test_review_fields_cannot_be_edited_in_the_form(admin_client, pattern):
    admin_client.post(
        f"{PATTERNS}{pattern.pk}/change/",
        pattern_form(pattern, status="approved", is_active="", usage_closed="on"),
    )

    pattern.refresh_from_db()
    assert (pattern.status, pattern.is_active, pattern.usage_closed) == (
        ReviewStatus.PENDING,
        True,
        False,
    )


def usage_form(usage, **changes):
    return {"explanation_ko": usage.explanation_ko, "example_ja": usage.example_ja, **changes}


def test_usage_explanation_and_example_can_be_edited(admin_client, pattern):
    usage = pattern.usages.get()

    response = admin_client.post(
        f"{USAGES}{usage.pk}/change/",
        usage_form(usage, explanation_ko="새 설명", example_ja="窓が開いている", status="approved"),
    )

    assert response.status_code == 302
    usage.refresh_from_db()
    assert (usage.explanation_ko, usage.example_ja, usage.status) == (
        "새 설명",
        "窓が開いている",
        ReviewStatus.PENDING,
    )


@pytest.mark.parametrize("example_ja", ["雨が降る", "⟨N1⟩人で走っている", "あ" * 200 + "ている"])
def test_usage_example_that_does_not_fit_is_not_saved(admin_client, pattern, example_ja):
    usage = pattern.usages.get()

    response = admin_client.post(
        f"{USAGES}{usage.pk}/change/", usage_form(usage, example_ja=example_ja)
    )

    assert response.status_code == 200
    usage.refresh_from_db()
    assert usage.example_ja == "雨が降っている"


def act(admin_client, url, action, *objects):
    return admin_client.post(
        url,
        {"action": action, "_selected_action": [obj.pk for obj in objects]},
        follow=True,
    )


def test_pattern_is_approved_with_an_admin_action(admin_client, pattern):
    GrammarPattern.objects.filter(pk=pattern.pk).update(
        test_cases=[
            {"text": "雨が降っている", "should_match": True},
            {"text": "雨が降る", "should_match": False},
        ]
    )

    act(admin_client, PATTERNS, "approve", pattern)

    pattern.refresh_from_db()
    assert pattern.status == ReviewStatus.APPROVED


def test_refused_action_shows_the_reason_and_changes_nothing(admin_client, pattern):
    response = act(admin_client, PATTERNS, "approve", pattern)

    pattern.refresh_from_db()
    assert pattern.status == ReviewStatus.PENDING
    page = html.unescape(response.content.decode())
    assert "'걸리면 안 됨' 예문이 없습니다" in page
    assert ORIGINAL not in page


@pytest.mark.parametrize(
    ("action", "status"),
    [("reject", ReviewStatus.REJECTED), ("approve", ReviewStatus.APPROVED)],
)
def test_usage_status_is_changed_with_admin_actions(admin_client, pattern, action, status):
    usage = pattern.usages.get()

    act(admin_client, USAGES, action, usage)

    usage.refresh_from_db()
    assert usage.status == status


def test_patterns_and_usages_are_not_added_or_deleted_in_admin(admin_client, pattern):
    usage = pattern.usages.get()

    assert admin_client.get(f"{PATTERNS}add/").status_code == 403
    assert admin_client.get(f"{USAGES}add/").status_code == 403
    assert admin_client.get(f"{PATTERNS}{pattern.pk}/delete/").status_code == 403
    assert admin_client.get(f"{USAGES}{usage.pk}/delete/").status_code == 403
    assert GrammarUsage.objects.count() == 1
