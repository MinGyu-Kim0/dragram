"""평가 결과에서 매칭 정정(FR-A21, #221·#222), 반려 시 건너뛰기와 멈춤·재개·목록(#223).
이음새는 admin 화면과 분석 API 응답이다.
"""

import pytest
from django.contrib.admin.models import LogEntry
from django.db import transaction
from django.urls import reverse

from accounts.withdrawal import withdraw
from analysis import patterns, review
from analysis.models import (
    EvalItem,
    EvalSentence,
    GrammarPattern,
    GrammarUsage,
    MatchCorrection,
    SentenceAnalysis,
    SpanMatch,
    UserSentence,
)
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, span_answer
from tests.analysis.test_colloquial import base_and_variant
from tests.analysis.test_evaluation import HASHITTEIRU, evaluate, new_pattern_response

pytestmark = pytest.mark.django_db


@pytest.fixture
def item(client, fake_llm, redis_db):
    """走っている를 평가해 ている를 '진행'으로 고른 평가 항목. ている 패턴엔 '결과 상태'도 있다."""
    new_pattern_response(fake_llm)
    analyze(client, HASHITTEIRU)
    with transaction.atomic():
        patterns.add_usage(GrammarPattern.objects.get(), "결과 상태", "결과가 남아 있다", None)
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": [span_answer(0, candidate_id=1)]}
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    evaluate("--yes")
    fake_llm.forget_requests()
    return EvalItem.objects.get()


def usage(name):
    return GrammarUsage.objects.get(name=name)


def correct_url(item):
    return reverse("admin:analysis_evalresult_correct", args=[item.result_id, item.pk])


def correct(admin_client, item, after):
    return admin_client.post(correct_url(item), {"after": after}, follow=True)


def test_correction_page_offers_the_usages_of_the_matched_pattern(admin_client, item):
    response = admin_client.get(correct_url(item))

    assert response.status_code == 200
    page = response.content.decode()
    assert "진행" in page and "결과 상태" in page and "매칭 해제" in page


def test_correction_makes_the_analysis_stale_and_is_logged(admin_client, admin_user, item):
    before = SentenceAnalysis.objects.get()

    correct(admin_client, item, usage("결과 상태").pk)

    correction = MatchCorrection.objects.get()
    assert (correction.start_offset, correction.end_offset) == (2, 5)
    assert correction.before_usage == usage("진행")
    assert correction.after_usage == usage("결과 상태")
    assert correction.status == MatchCorrection.Status.ACTIVE
    assert correction.corrected_by == admin_user
    after = SentenceAnalysis.objects.get()
    assert after.is_stale is True
    assert after.generation == before.generation + 1
    assert LogEntry.objects.filter(object_id=str(correction.pk), user=admin_user).exists()


def test_correcting_the_same_span_again_changes_the_one_row(admin_client, item):
    correct(admin_client, item, usage("결과 상태").pk)
    correct(admin_client, item, "release")

    correction = MatchCorrection.objects.get()
    assert correction.after_usage is None
    # 정정 전 용법은 처음 정정한 때의 LLM 판정이다.
    assert correction.before_usage == usage("진행")


def test_corrected_span_wins_over_the_llm_and_is_not_asked(client, fake_llm, admin_client, item):
    correct(admin_client, item, usage("결과 상태").pk)
    # 정정한 구간은 묻지 않으므로 LLM이 그 구간을 다시 고를 수 없다(묻지 않은 구간의 답은 검증에
    # 걸린다). 확정 구간으로 알려 번역이 정정한 해석을 따르게 한다.
    fake_llm.response = {"translation_ko": "달려 있다"}

    response = analyze(client, HASHITTEIRU)

    [request] = fake_llm.requests
    assert request["spans"] == []
    assert request["decided_spans"] == [
        {"start_token_id": 1, "end_token_id": 2, "name": "결과 상태"}
    ]
    [grammar] = response.json()["grammar"]
    assert (grammar["start"], grammar["end"], grammar["name"]) == (2, 5, "결과 상태")
    # 정정 후 용법이 미검수라 미검수로 보인다.
    assert grammar["review_status"] == "pending"
    row = SpanMatch.objects.get()
    assert (row.usage, row.decided_by) == (usage("결과 상태"), SpanMatch.DecidedBy.ADMIN)
    assert response.json()["translation_ko"] == "달려 있다"


def test_released_span_is_left_out(client, fake_llm, admin_client, item):
    correct(admin_client, item, "release")
    fake_llm.response = {"translation_ko": "달리고 있다"}

    response = analyze(client, HASHITTEIRU)

    [request] = fake_llm.requests
    assert (request["spans"], request["decided_spans"]) == ([], [])
    assert response.json()["grammar"] == []
    assert not SpanMatch.objects.exists()


def test_released_span_is_not_proposed_again_as_a_new_pattern(client, fake_llm, admin_client, item):
    correct(admin_client, item, "release")
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [new_pattern((1, "lemma"), (2, "lemma"))],
    }

    response = analyze(client, HASHITTEIRU)

    assert response.json()["grammar"] == []
    assert GrammarPattern.objects.count() == 1


def test_usage_outside_the_choices_is_refused(admin_client, item):
    other = GrammarPattern.objects.create(
        name="で", morpheme_key="other", is_active=True, status="pending"
    )
    stranger = GrammarUsage.objects.create(
        pattern=other, name="수단", explanation_ko="수단", status="pending", origin="llm"
    )

    response = correct(admin_client, item, stranger.pk)

    assert "고를 수 없는 용법" in response.content.decode()
    assert not MatchCorrection.objects.exists()
    assert SentenceAnalysis.objects.get().is_stale is False


@pytest.mark.parametrize("status", [SentenceAnalysis.Status.PROCESSING, "missing"])
def test_correction_needs_a_complete_analysis(admin_client, item, status):
    if status == "missing":
        UserSentence.objects.all().delete()
        SentenceAnalysis.objects.all().delete()
    else:
        SentenceAnalysis.objects.update(status=status)

    response = correct(admin_client, item, usage("결과 상태").pk)

    assert "분석이 없거나 처리 중" in response.content.decode()
    assert not MatchCorrection.objects.exists()


def test_result_page_links_each_item_to_its_correction(admin_client, item):
    response = admin_client.get(reverse("admin:analysis_evalresult_change", args=[item.result_id]))

    assert correct_url(item) in response.content.decode()


def test_correction_outlives_the_admin_who_made_it(admin_client, admin_user, item):
    correct(admin_client, item, usage("결과 상태").pk)

    withdraw(admin_user)

    assert MatchCorrection.objects.get().corrected_by is None


def test_release_leaves_another_pattern_at_the_same_place(client, fake_llm, admin_client, item):
    # 같은 자리(ている)에 걸리는 다른 패턴. 승인된 용법 완결 패턴이라 LLM 없이 정해진다.
    first, *rest = patterns.conditions_of(item_pattern())
    conditions = [first._replace(lemma=None), *rest]
    with transaction.atomic():
        other, _ = patterns.register(
            conditions, "ている(넓게)", "상태", "상태를 나타낸다", None, HASHITTEIRU
        )
        patterns.raise_pattern_set_version()
    GrammarPattern.objects.filter(pk=other.pk).update(status="approved", usage_closed=True)
    other.usages.update(status="approved")
    correct(admin_client, item, "release")
    fake_llm.response = {"translation_ko": "달리고 있다"}

    response = analyze(client, HASHITTEIRU)

    assert [g["pattern_name"] for g in response.json()["grammar"]] == ["ている(넓게)"]


def item_pattern():
    return GrammarPattern.objects.get(name="ている")


def previous_names(response):
    """stale 재분석 스트림의 previous 이벤트에 보인 문법 이름(#222)."""
    first = response.events[0]
    assert first["type"] == "previous"
    return [g["name"] for g in first["grammar"]]


def test_previous_result_shows_the_corrected_usage(client, fake_llm, admin_client, item):
    correct(admin_client, item, usage("결과 상태").pk)
    fake_llm.response = {"translation_ko": "달려 있다"}

    response = analyze(client, HASHITTEIRU)

    assert previous_names(response) == ["결과 상태"]
    # 번역은 기존 규칙대로 옛 번역을 그대로 보인다.
    assert response.events[0]["translation_ko"] == "달리고 있다"


def test_previous_result_leaves_out_a_released_span(client, fake_llm, admin_client, item):
    correct(admin_client, item, "release")

    response = analyze(client, HASHITTEIRU)

    assert previous_names(response) == []


def test_failed_reanalysis_does_not_bring_the_wrong_answer_back(
    client, fake_llm, admin_client, item
):
    correct(admin_client, item, usage("결과 상태").pk)
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    first = analyze(client, HASHITTEIRU)
    again = analyze(client, HASHITTEIRU)

    assert first.json() == {"error": "ANALYSIS:FAILED"}
    # 실패한 시도는 저장하지 않아 옛 구간이 남지만, 다시 와도 정정 결과로 보인다.
    assert previous_names(first) == previous_names(again) == ["결과 상태"]
    assert SpanMatch.objects.get().usage == usage("진행")


def test_suspended_correction_leaves_the_previous_result_as_it_was(
    client, fake_llm, admin_client, item
):
    correct(admin_client, item, usage("결과 상태").pk)
    MatchCorrection.objects.update(status=MatchCorrection.Status.SUSPENDED)
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": [span_answer(0, candidate_id=1)]}

    response = analyze(client, HASHITTEIRU)

    assert previous_names(response) == ["진행"]


def test_previous_result_skips_a_correction_to_a_rejected_usage(
    client, fake_llm, admin_client, item
):
    # 재분석이 정정을 건너뛰듯(정정 후 용법이 후보에 없음) 옛 결과도 원래 판정을 보인다.
    correct(admin_client, item, usage("결과 상태").pk)
    GrammarUsage.objects.filter(name="결과 상태").update(status="rejected")
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": [span_answer(0, candidate_id=1)]}

    response = analyze(client, HASHITTEIRU)

    assert previous_names(response) == ["진행"]


CORRECTIONS = "/admin/analysis/matchcorrection/"
# 토큰: 0 食べ / 1 ちゃっ / 2 た
TABECHATTA = "食べちゃった"


@pytest.fixture
def colloquial_item(client, fake_llm, redis_db):
    """원형 てしまう(완료·유감)에 연결된 회화체 ちゃう 구간을 평가한 항목. '완료'로 골랐다."""
    base, variant = base_and_variant(fake_llm)
    review.link_variant(variant, base)
    with transaction.atomic():
        patterns.add_usage(base, "유감", "아쉬움을 나타낸다", None)
    EvalSentence.objects.create(text=TABECHATTA, category="normal")
    fake_llm.response = {"translation_ko": "먹어 버렸다", "spans": [span_answer(0, candidate_id=1)]}
    evaluate("--yes")
    fake_llm.forget_requests()
    return EvalItem.objects.get(surface="ちゃっ")


def names(response):
    return [g["name"] for g in response.json()["grammar"]]


def test_correction_to_a_rejected_usage_is_skipped_until_unrejected(
    client, fake_llm, admin_client, item
):
    correct(admin_client, item, usage("결과 상태").pk)
    review.reject_usage(usage("결과 상태"))
    # 정정을 건너뛰어 그 구간을 다시 LLM에 묻는다.
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": [span_answer(0, candidate_id=1)]}

    assert names(analyze(client, HASHITTEIRU)) == ["진행"]
    assert MatchCorrection.objects.get().status == MatchCorrection.Status.ACTIVE

    review.unreject_usage(usage("결과 상태"))
    fake_llm.response = {"translation_ko": "달려 있다"}

    assert names(analyze(client, HASHITTEIRU)) == ["결과 상태"]


def test_correction_of_a_rejected_pattern_is_skipped_until_unrejected(
    client, fake_llm, admin_client, item
):
    # 정정 후 용법의 소속 패턴이 곧 실제 매칭 패턴이다.
    correct(admin_client, item, usage("결과 상태").pk)
    teiru = GrammarPattern.objects.get(name="ている")
    review.reject_pattern(teiru)
    fake_llm.response = {"translation_ko": "달리고 있다"}

    assert names(analyze(client, HASHITTEIRU)) == []
    assert MatchCorrection.objects.get().status == MatchCorrection.Status.ACTIVE

    review.unreject_pattern(teiru)

    assert names(analyze(client, HASHITTEIRU)) == ["결과 상태"]


@pytest.mark.parametrize("rejected", ["ちゃう", "てしまう"])
def test_correction_of_a_colloquial_span_is_skipped_while_either_pattern_is_rejected(
    client, fake_llm, admin_client, colloquial_item, rejected
):
    # ちゃう는 실제 매칭 패턴, てしまう는 연결된 원형이자 정정 후 용법의 소속 패턴이다.
    correct(admin_client, colloquial_item, usage("유감").pk)
    pattern = GrammarPattern.objects.get(name=rejected)
    review.reject_pattern(pattern)
    fake_llm.response = {"translation_ko": "먹어 버렸다"}

    assert names(analyze(client, TABECHATTA)) == []
    assert MatchCorrection.objects.get().status == MatchCorrection.Status.ACTIVE

    review.unreject_pattern(pattern)

    assert names(analyze(client, TABECHATTA)) == ["유감"]


def act(admin_client, action, correction):
    return admin_client.post(
        CORRECTIONS, {"action": action, "_selected_action": [correction.pk]}, follow=True
    )


def test_suspending_and_activating_a_correction(client, fake_llm, admin_client, item):
    correct(admin_client, item, usage("결과 상태").pk)
    correction = MatchCorrection.objects.get()
    analyze(client, HASHITTEIRU)
    before = SentenceAnalysis.objects.get()

    act(admin_client, "suspend_corrections", correction)

    correction.refresh_from_db()
    after = SentenceAnalysis.objects.get()
    assert correction.status == MatchCorrection.Status.SUSPENDED
    assert (after.is_stale, after.generation) == (True, before.generation + 1)
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": [span_answer(0, candidate_id=1)]}
    assert names(analyze(client, HASHITTEIRU)) == ["진행"]

    act(admin_client, "activate_corrections", correction)

    correction.refresh_from_db()
    assert correction.status == MatchCorrection.Status.ACTIVE
    assert SentenceAnalysis.objects.get().is_stale is True
    fake_llm.response = {"translation_ko": "달려 있다"}
    assert names(analyze(client, HASHITTEIRU)) == ["결과 상태"]


def test_correction_list_shows_who_when_what_without_the_sentence(admin_client, admin_user, item):
    correct(admin_client, item, usage("결과 상태").pk)

    page = admin_client.get(CORRECTIONS).content.decode()

    assert admin_user.username in page
    assert "진행" in page and "결과 상태" in page and "적용" in page
    # 공용 분석을 가리킬 뿐, 문장(평가 문장도)은 보이지 않는다.
    assert HASHITTEIRU not in page


def test_corrections_are_not_added_or_deleted_in_admin(admin_client, item):
    correct(admin_client, item, "release")
    correction = MatchCorrection.objects.get()

    assert admin_client.get(f"{CORRECTIONS}add/").status_code == 403
    assert admin_client.get(f"{CORRECTIONS}{correction.pk}/delete/").status_code == 403
