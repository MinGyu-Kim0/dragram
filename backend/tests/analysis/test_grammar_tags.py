"""문법 용법의 품사 태그와 기능 태그(#151)."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import transaction

from analysis import llm, patterns, review
from analysis.models import FunctionTag, GrammarPattern, GrammarUsage, ReviewStatus
from tests.analysis.helpers import analyze, new_pattern, new_usage, pattern_form, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
HASHITTEIRU = "走っている"
# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"
USAGES = "/admin/analysis/grammarusage/"


def teiru(function_tags=("progressive",)):
    return {**new_pattern((1, "lemma"), (2, "lemma")), "function_tags": list(function_tags)}


def registered(client, fake_llm, function_tags=("progressive",)):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [teiru(function_tags)]}
    return analyze(client, HASHITTEIRU)


def test_new_usage_keeps_only_allowed_function_tags_and_is_still_registered(client, fake_llm):
    response = registered(
        client, fake_llm, ["resultative", "unknown", "progressive", "progressive"]
    )

    usage = GrammarUsage.objects.get()
    # 허용 목록 순서로, 중복 없이
    assert usage.function_tags == ["progressive", "resultative"]
    assert usage.function_tags_filled
    assert usage.function_tags_status == ReviewStatus.PENDING
    [item] = response.json()["grammar"]
    assert item["function_tags"] == ["progressive", "resultative"]
    assert item["function_tags_review_status"] == "pending"


@pytest.mark.parametrize("function_tags", [[], ["unknown"], None, "progressive", [7]])
def test_bad_or_empty_function_tags_are_stored_empty(client, fake_llm, function_tags):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [
            {**new_pattern((1, "lemma"), (2, "lemma")), "function_tags": function_tags}
        ],
    }

    response = analyze(client, HASHITTEIRU)

    usage = GrammarUsage.objects.get()
    assert (usage.function_tags, usage.function_tags_filled) == ([], True)
    assert usage.function_tags_status is None
    assert response.json()["grammar"][0]["function_tags"] == []


def test_grammar_items_carry_part_of_speech_tags_in_order_without_any_tokens(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [
            # て + 居る
            new_pattern((3, "lemma"), (4, "lemma"), example_ja="雨が降っている"),
            # が + 아무거나 + て: 아무거나(来る, 동사)는 빠지고 조사는 한 번만
            new_pattern(
                (1, "lemma"),
                (2, "any"),
                (3, "lemma"),
                pattern_name="が〜て",
                usage_name="주어",
                example_ja="雨が降って寒い",
            ),
        ],
    }

    response = analyze(client, KITEIRU)

    tags = {item["name"]: item["pos_tags"] for item in response.json()["grammar"]}
    assert tags == {"진행": ["particle", "verb"], "주어": ["particle"]}


def test_auxiliary_verbs_are_tagged(client, fake_llm):
    # 토큰: 0 勝ち / 1 まし / 2 た
    fake_llm.response = {
        "translation_ko": "이겼습니다",
        "new_patterns": [
            new_pattern(
                (1, "lemma"),
                (2, "lemma"),
                pattern_name="ました",
                usage_name="정중한 과거",
                example_ja="本を読みました",
            )
        ],
    }

    [item] = analyze(client, "勝ちました").json()["grammar"]

    assert item["pos_tags"] == ["auxiliary_verb"]


def test_unfound_span_usage_stores_its_function_tags(client, fake_llm):
    registered(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [
            span_answer(
                0,
                "unfound",
                new_usage=new_usage(
                    usage_name="결과 상태",
                    explanation_ko="동작의 결과가 남아 있다",
                    example_ja="窓が開いている",
                )
                | {"function_tags": ["resultative", "nope"]},
            )
        ],
    }

    response = analyze(client, KITEIRU)

    assert GrammarUsage.objects.get(name="결과 상태").function_tags == ["resultative"]
    assert response.json()["grammar"][0]["function_tags"] == ["resultative"]


def test_alternatives_carry_their_function_tags(client, fake_llm):
    registered(client, fake_llm)
    pattern = GrammarPattern.objects.get()
    with transaction.atomic():
        patterns.add_usage(
            pattern, "결과 상태", "동작의 결과가 남아 있다", None, function_tags=["resultative"]
        )
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [
            {
                **span_answer(0, "divergent", 1),
                "alternatives": [
                    {
                        "candidate_id": 2,
                        "translation_ko": "그가 와 있는 상태다",
                        "basis": "앞에서 이미 도착했다고 말했다면",
                    }
                ],
            }
        ],
    }

    [item] = analyze(client, KITEIRU).json()["grammar"]

    assert item["function_tags"] == ["progressive"]
    [alternative] = item["alternatives"]
    assert alternative["function_tags"] == ["resultative"]
    assert alternative["function_tags_review_status"] == "pending"


def test_admin_cannot_save_a_function_tag_outside_the_allowed_list(admin_client, client, fake_llm):
    registered(client, fake_llm)
    usage = GrammarUsage.objects.get()
    form = {"explanation_ko": usage.explanation_ko, "example_ja": usage.example_ja or ""}

    response = admin_client.post(
        f"{USAGES}{usage.pk}/change/", {**form, "function_tags": ["progressive", "unknown"]}
    )

    assert response.status_code == 200
    usage.refresh_from_db()
    assert usage.function_tags == ["progressive"]

    admin_client.post(f"{USAGES}{usage.pk}/change/", {**form, "function_tags": ["past"]})
    usage.refresh_from_db()
    assert usage.function_tags == ["past"]
    # 관리자가 고친 태그는 검수한 것이다.
    assert usage.function_tags_status == ReviewStatus.APPROVED

    admin_client.post(f"{USAGES}{usage.pk}/change/", form)
    usage.refresh_from_db()
    assert (usage.function_tags, usage.function_tags_status) == ([], None)
    assert usage.function_tags_filled


def test_admin_edit_on_the_pattern_page_marks_the_function_tags_filled(
    admin_client, client, fake_llm
):
    registered(client, fake_llm, [])
    GrammarUsage.objects.update(function_tags_filled=False)
    pattern = GrammarPattern.objects.get()

    admin_client.post(
        f"/admin/analysis/grammarpattern/{pattern.pk}/change/",
        pattern_form(pattern, **{"usages-0-function_tags": ["progressive"]}),
    )

    usage = GrammarUsage.objects.get()
    assert usage.function_tags == ["progressive"]
    assert usage.function_tags_filled
    assert usage.function_tags_status == ReviewStatus.APPROVED


def test_approving_the_usage_approves_its_function_tags(client, fake_llm):
    registered(client, fake_llm)
    usage = GrammarUsage.objects.get()
    # 패턴 승인 조건(test_cases)은 이 테스트의 관심이 아니다.
    GrammarPattern.objects.update(status=ReviewStatus.APPROVED)

    review.approve_usage(usage)

    usage.refresh_from_db()
    assert usage.function_tags_status == ReviewStatus.APPROVED


def test_admin_approves_unreviewed_function_tags(admin_client, client, fake_llm):
    registered(client, fake_llm)
    usage = GrammarUsage.objects.get()
    review.approve_usage(usage)
    GrammarUsage.objects.update(function_tags_status=ReviewStatus.PENDING)

    admin_client.post(USAGES, {"action": "approve_function_tags", "_selected_action": [usage.pk]})

    usage.refresh_from_db()
    assert usage.function_tags_status == ReviewStatus.APPROVED


def test_function_tags_without_pending_values_cannot_be_approved(client, fake_llm):
    registered(client, fake_llm, [])

    with pytest.raises(review.Refused):
        review.approve_function_tags(GrammarUsage.objects.get())


def fill(**options):
    out = StringIO()
    call_command("fill_usages", stdout=out, stderr=out, **options)
    return out.getvalue()


def test_fill_command_fills_only_unfilled_function_tags_and_keeps_the_usage_status(
    client, fake_llm
):
    registered(client, fake_llm)
    usage = GrammarUsage.objects.get()
    GrammarPattern.objects.update(status=ReviewStatus.APPROVED)
    review.approve_usage(usage)
    # 대응 표현은 채웠고 기능 태그만 채운 적 없는 용법
    GrammarUsage.objects.update(
        function_tags=[], function_tags_status=None, function_tags_filled=False
    )
    fake_llm.fill_response = {
        "usages": [
            {
                "usage_id": usage.pk,
                "korean_equivalent": "~는 중이다",
                "function_tags": ["progressive", "unknown"],
            }
        ]
    }

    fill()

    usage.refresh_from_db()
    assert usage.function_tags == ["progressive"]
    assert usage.function_tags_filled
    # 승인된 용법이라도 나중에 채운 태그는 따로 승인할 때까지 미검수다.
    assert (usage.status, usage.function_tags_status) == (
        ReviewStatus.APPROVED,
        ReviewStatus.PENDING,
    )
    # 이미 채운 대응 표현은 덮지 않는다.
    assert usage.korean_equivalent is None

    fill()

    assert len(fake_llm.fill_requests) == 1


def test_fill_request_gives_pattern_morphemes_but_no_sentence_original(client, fake_llm):
    registered(client, fake_llm)
    GrammarUsage.objects.update(function_tags_filled=False)

    fill()

    [[request]] = fake_llm.fill_requests
    assert request["morphemes"] == [
        {"lemma": "て", "pos1": "助詞", "conjugation_form": None},
        {"lemma": "居る", "pos1": "動詞", "conjugation_form": None},
    ]
    assert HASHITTEIRU not in json.dumps(fake_llm.fill_requests, ensure_ascii=False)


def test_every_new_usage_answer_asks_for_allowed_function_tags():
    new_pattern_schema = llm.RESPONSE_SCHEMA["properties"]["new_patterns"]["items"]
    [new_usage_schema, _] = llm.span_answers_schema(True)["items"]["properties"]["new_usage"][
        "anyOf"
    ]
    fill_schema = llm.FILL_SCHEMA["properties"]["usages"]["items"]
    for schema in (new_pattern_schema, new_usage_schema, fill_schema):
        assert "function_tags" in schema["required"]
        assert schema["properties"]["function_tags"]["items"]["enum"] == FunctionTag.values
    for instructions in (llm.INSTRUCTIONS, llm.JUDGE_INSTRUCTIONS, llm.FILL_INSTRUCTIONS):
        assert llm.FUNCTION_TAGS_RULE in instructions
