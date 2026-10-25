"""문법 용법의 한국어 대응 표현(#152)."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import transaction

from analysis import patterns
from analysis.models import GrammarPattern, GrammarUsage, ReviewStatus, UsageLog
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, new_usage, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
HASHITTEIRU = "走っている"
# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"
USAGES = "/admin/analysis/grammarusage/"


def teiru(korean_equivalent="~고 있다"):
    return {
        **new_pattern((1, "lemma"), (2, "lemma")),
        "korean_equivalent": korean_equivalent,
    }


def registered(client, fake_llm, korean_equivalent="~고 있다"):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [teiru(korean_equivalent)],
    }
    return analyze(client, HASHITTEIRU)


def test_new_pattern_usage_stores_its_korean_equivalent_and_shows_it(client, fake_llm):
    response = registered(client, fake_llm)

    usage = GrammarUsage.objects.get()
    assert usage.korean_equivalent == "~고 있다"
    assert usage.korean_equivalent_filled
    [item] = response.json()["grammar"]
    assert item["korean_equivalent"] == "~고 있다"


def test_cached_sentence_shows_the_korean_equivalent(client, fake_llm):
    registered(client, fake_llm)

    response = analyze(client, HASHITTEIRU)

    assert response.types() == ["translation", "analysis"]
    assert response.json()["grammar"][0]["korean_equivalent"] == "~고 있다"


def test_unfound_span_usage_stores_its_korean_equivalent(client, fake_llm):
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
                | {"korean_equivalent": "~어 있다"},
            )
        ],
    }

    response = analyze(client, KITEIRU)

    added = GrammarUsage.objects.get(name="결과 상태")
    assert added.korean_equivalent == "~어 있다"
    assert added.korean_equivalent_filled
    assert response.json()["grammar"][0]["korean_equivalent"] == "~어 있다"


@pytest.mark.parametrize(
    "korean_equivalent",
    [
        "",
        "   ",
        # 문장 전체를 옮김
        "走っている → 달리고 있다",
        # 숫자 자리표시자
        "~⟨N1⟩번 하고 있다",
        # 상한(100자) 넘음
        "~고 있다" + " · ~고 있다" * 20,
        None,
        7,
    ],
)
def test_bad_korean_equivalent_is_left_empty_and_the_usage_is_still_registered(
    client, fake_llm, korean_equivalent
):
    response = registered(client, fake_llm, korean_equivalent)

    usage = GrammarUsage.objects.get()
    assert usage.korean_equivalent is None
    assert usage.korean_equivalent_filled
    [item] = response.json()["grammar"]
    assert item["name"] == "진행"
    assert item["korean_equivalent"] is None


def test_korean_equivalent_may_name_a_typical_verb(client, fake_llm):
    registered(client, fake_llm, "~에게 · ~을/를 (会う·乗る 등)")

    assert GrammarUsage.objects.get().korean_equivalent == "~에게 · ~을/를 (会う·乗る 등)"


def test_missing_korean_equivalent_is_stored_empty(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [new_pattern((1, "lemma"), (2, "lemma"))],
    }

    analyze(client, HASHITTEIRU)

    assert GrammarUsage.objects.get().korean_equivalent is None


def test_alternatives_carry_their_korean_equivalent(client, fake_llm):
    registered(client, fake_llm)
    pattern = GrammarPattern.objects.get()
    with transaction.atomic():
        result, _ = patterns.add_usage(
            pattern, "결과 상태", "동작의 결과가 남아 있다", None, korean_equivalent="~어 있다"
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

    response = analyze(client, KITEIRU)

    [item] = response.json()["grammar"]
    assert item["korean_equivalent"] == "~고 있다"
    [alternative] = item["alternatives"]
    assert alternative["name"] == result.name
    assert alternative["korean_equivalent"] == "~어 있다"


def test_admin_can_edit_the_korean_equivalent(admin_client, client, fake_llm):
    registered(client, fake_llm)
    usage = GrammarUsage.objects.get()
    form = {"explanation_ko": usage.explanation_ko, "example_ja": usage.example_ja or ""}

    admin_client.post(f"{USAGES}{usage.pk}/change/", {**form, "korean_equivalent": "~는 중이다"})
    usage.refresh_from_db()
    assert usage.korean_equivalent == "~는 중이다"

    admin_client.post(f"{USAGES}{usage.pk}/change/", {**form, "korean_equivalent": ""})
    usage.refresh_from_db()
    assert usage.korean_equivalent is None
    assert usage.korean_equivalent_filled


def unfilled_usage(name="진행", status=ReviewStatus.PENDING):
    """대응 표현을 채운 적 없는 용법(이 기능 전에 만든 용법처럼)."""
    pattern, _ = GrammarPattern.objects.get_or_create(
        morpheme_key="k",
        defaults={"name": "ている", "status": ReviewStatus.PENDING, "is_active": False},
    )
    return GrammarUsage.objects.create(
        pattern=pattern,
        name=name,
        explanation_ko=f"{name} 설명",
        example_ja="雨が降っている",
        status=status,
        origin=GrammarUsage.Origin.ADMIN,
    )


def fill(**options):
    out = StringIO()
    call_command("fill_usages", stdout=out, stderr=out, **options)
    return out.getvalue()


def test_fill_command_fills_only_unfilled_usages_without_any_sentence(fake_llm):
    progress = unfilled_usage()
    done = unfilled_usage("결과 상태")
    GrammarUsage.objects.filter(pk=done.pk).update(
        korean_equivalent="~어 있다", korean_equivalent_filled=True
    )
    fake_llm.fill_response = {
        "usages": [{"usage_id": progress.pk, "korean_equivalent": "~고 있다"}]
    }

    fill()

    [request] = fake_llm.fill_requests
    assert request == [
        {
            "usage_id": progress.pk,
            "pattern_name": "ている",
            "usage_name": "진행",
            "explanation_ko": "진행 설명",
            "example_ja": "雨が降っている",
        }
    ]
    progress.refresh_from_db()
    assert progress.korean_equivalent == "~고 있다"
    assert progress.korean_equivalent_filled
    assert GrammarUsage.objects.get(pk=done.pk).korean_equivalent == "~어 있다"
    [row] = UsageLog.objects.all()
    assert (row.kind, row.purpose, row.user) == ("llm", "usage_fill", None)

    fill()

    assert len(fake_llm.fill_requests) == 1


def test_fill_command_skips_rejected_usages(fake_llm):
    unfilled_usage(status=ReviewStatus.REJECTED)

    fill()

    assert fake_llm.fill_requests == []


def test_fill_command_leaves_bad_answers_empty_and_unanswered_usages_unfilled(fake_llm):
    bad, missing = unfilled_usage(), unfilled_usage("결과 상태")
    fake_llm.fill_response = {
        "usages": [
            {"usage_id": bad.pk, "korean_equivalent": "~⟨N1⟩번"},
            # 요청하지 않은 용법은 무시한다.
            {"usage_id": 999_999, "korean_equivalent": "~에"},
        ]
    }

    fill()

    bad.refresh_from_db()
    missing.refresh_from_db()
    assert (bad.korean_equivalent, bad.korean_equivalent_filled) == (None, True)
    assert (missing.korean_equivalent, missing.korean_equivalent_filled) == (None, False)


def test_fill_command_asks_in_batches(fake_llm):
    usages = [unfilled_usage(f"용법 {i}") for i in range(3)]

    fill(batch=2)

    assert [len(request) for request in fake_llm.fill_requests] == [2, 1]
    assert all(
        usage.korean_equivalent_filled
        for usage in GrammarUsage.objects.filter(pk__in=[u.pk for u in usages])
    )


def test_fill_command_reports_a_failed_call_and_goes_on(fake_llm):
    first, second = unfilled_usage(), unfilled_usage("결과 상태")
    fake_llm.fill_errors = [BusinessError(AnalysisError.FAILED, "LLM 호출 실패")]

    output = fill(batch=1)

    assert "실패" in output
    first.refresh_from_db()
    second.refresh_from_db()
    assert not first.korean_equivalent_filled
    assert second.korean_equivalent_filled


def test_fill_request_has_no_sentence_original(client, fake_llm):
    registered(client, fake_llm)
    GrammarUsage.objects.update(korean_equivalent=None, korean_equivalent_filled=False)

    fill()

    assert HASHITTEIRU not in json.dumps(fake_llm.fill_requests, ensure_ascii=False)
