"""분석 요청·LLM 호출 사용 기록(usage_log, #94)."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import F

from analysis import views
from analysis.models import SentenceAnalysis, UsageLog
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, span_answer
from tests.analysis.test_rematch import GA, KITEIRU, cache_then_register_teiru, register

pytestmark = pytest.mark.django_db

# 토큰: 0 昨日 / 1 図書館 / 2 で / 3 本 / 4 を / 5 読ん / 6 で / 7 いる
LIBRARY = "昨日図書館で本を読んでいる"


def rows():
    """(종류, 경로, 목적, 성공) 기록 순서대로"""
    return list(UsageLog.objects.order_by("id").values_list("kind", "path", "purpose", "success"))


def forget_rows(fake_llm):
    """준비 단계의 기록을 지운다."""
    UsageLog.objects.all().delete()
    fake_llm.forget_requests()


def test_new_sentence_records_the_request_and_its_llm_call(client, fake_llm, analyst):
    fake_llm.usage = (120, 30, 15)

    analyze(client, KITEIRU)

    analysis = SentenceAnalysis.objects.get()
    assert rows() == [("request", "llm", None, True), ("llm", None, "first_response", True)]
    request, call = UsageLog.objects.order_by("id")
    assert request.analysis == call.analysis == analysis
    assert (call.model, call.input_tokens, call.cached_input_tokens, call.output_tokens) == (
        "fake-model",
        120,
        30,
        15,
    )
    assert call.attempt == 1
    # 확장 토큰의 주인이 요청과 LLM 호출 기록에 남는다(#109).
    assert request.user == call.user == analyst


def test_asking_again_records_each_follow_up_call(client, fake_llm):
    register(fake_llm, "走っている", new_pattern((1, "lemma"), (2, "lemma")))
    forget_rows(fake_llm)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "unresolved")]}
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "usage", 1)],
    }

    analyze(client, KITEIRU)

    assert rows() == [
        ("request", "llm", None, True),
        ("llm", None, "first_response", True),
        ("llm", None, "reask", True),
    ]
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert set(UsageLog.objects.values_list("analysis", flat=True)) == {analysis.pk}


def test_rewriting_a_copied_example_is_recorded(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }

    analyze(client, LIBRARY)

    assert rows() == [
        ("request", "llm", None, True),
        ("llm", None, "first_response", True),
        ("llm", None, "example_rewrite", True),
    ]


def test_cached_sentence_records_a_cache_request_without_llm_calls(client, fake_llm):
    analyze(client, KITEIRU)
    forget_rows(fake_llm)

    analyze(client, KITEIRU)

    assert rows() == [("request", "cache", None, True)]
    assert UsageLog.objects.get().analysis == SentenceAnalysis.objects.get()


def test_rematch_decided_without_llm_records_a_db_request(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")
    register(fake_llm, "雨が降る", GA)
    forget_rows(fake_llm)

    analyze(client, "走っている")

    assert fake_llm.all_requests() == []
    assert rows() == [("request", "db", None, True)]
    assert UsageLog.objects.get().analysis == SentenceAnalysis.objects.get(
        translation_ko="달리고 있다"
    )


def test_rematch_judge_records_an_llm_request_and_the_judge_call(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    UsageLog.objects.all().delete()
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}

    analyze(client, KITEIRU)

    assert rows() == [("request", "llm", None, True), ("llm", None, "rematch_judge", True)]
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert set(UsageLog.objects.values_list("analysis", flat=True)) == {analysis.pk}


def test_failed_rematch_judge_records_a_failed_request(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    UsageLog.objects.all().delete()
    fake_llm.rematch_error = BusinessError(AnalysisError.FAILED, "LLM 재판정 호출 실패")

    analyze(client, KITEIRU)

    assert rows() == [("request", "llm", None, False), ("llm", None, "rematch_judge", False)]


def test_failed_llm_call_is_recorded_and_the_request_fails(client, fake_llm):
    fake_llm.error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    analyze(client, KITEIRU)

    assert rows() == [("request", "llm", None, False), ("llm", None, "first_response", False)]
    # 선점할 때 처리 중 행을 먼저 만들므로 실패한 시도도 그 행에 잇는다(#98).
    failed = SentenceAnalysis.objects.get(status="failed")
    assert set(UsageLog.objects.values_list("analysis", flat=True)) == {failed.pk}


def test_rejected_llm_answer_keeps_the_call_on_the_failed_analysis(client, fake_llm):
    # 호출 자체는 성공했지만 검증에서 거부돼 저장하지 않았다.
    fake_llm.response = {"translation_ko": 1}

    analyze(client, KITEIRU)

    assert rows() == [("request", "llm", None, False), ("llm", None, "first_response", True)]
    failed = SentenceAnalysis.objects.get(status="failed")
    assert set(UsageLog.objects.values_list("analysis", flat=True)) == {failed.pk}


def test_llm_call_stays_recorded_when_the_save_is_rolled_back(client, fake_llm):
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, KITEIRU)
    SentenceAnalysis.objects.update(is_stale=True)
    forget_rows(fake_llm)
    # 다시 분석하는 사이 영향 범위가 바뀌어 저장을 되돌린다.
    fake_llm.before_respond = lambda: SentenceAnalysis.objects.update(
        generation=F("generation") + 1
    )
    fake_llm.response = {"translation_ko": "그가 와 있어"}

    analyze(client, KITEIRU)

    analysis = SentenceAnalysis.objects.get()
    assert (analysis.is_stale, analysis.translation_ko) == (True, "그가 와 있다")
    # 저장하지 않은 결과는 보내지 않고 실패로 알리므로 요청도 실패다(#98).
    assert rows() == [("request", "llm", None, False), ("llm", None, "first_response", True)]
    assert set(UsageLog.objects.values_list("analysis", flat=True)) == {analysis.pk}


def test_new_sentence_whose_save_is_rolled_back_keeps_its_calls_on_the_failed_analysis(
    client, fake_llm, monkeypatch
):
    # 분석하는 사이 판별 규칙이 바뀌어 새 분석 행까지 되돌린다.
    monkeypatch.setattr(views, "_basis_changed", lambda *_: True)

    analyze(client, KITEIRU)

    failed = SentenceAnalysis.objects.get()
    assert (failed.status, failed.word_spans) == ("failed", None)
    assert rows() == [("request", "llm", None, False), ("llm", None, "first_response", True)]
    assert set(UsageLog.objects.values_list("analysis", flat=True)) == {failed.pk}


def test_records_hold_no_original_text(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "어제 도서관에서 책을 읽고 있다",
        "new_patterns": [
            new_pattern((6, "lemma"), (7, "lemma"), example_ja="昨日図書館で本を見ている")
        ],
    }

    analyze(client, LIBRARY)
    analyze(client, LIBRARY)

    values = repr(list(UsageLog.objects.values()))
    assert len(UsageLog.objects.all()) == 4
    for part in ("昨日", "図書館", "本", "読ん", "어제 도서관"):
        assert part not in values


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "request", "path": None},
        {"kind": "request", "path": "llm", "purpose": "first_response"},
        {"kind": "llm", "purpose": None},
        {"kind": "llm", "purpose": "reask", "path": "llm"},
        {"kind": "other", "path": "llm"},
    ],
)
def test_record_kind_decides_which_of_path_and_purpose_it_has(fields):
    # request에는 처리 경로만, llm에는 호출 목적만 있다. 집계가 조용히 오염되지 않게 DB가 막는다.
    with pytest.raises(IntegrityError), transaction.atomic():
        UsageLog.objects.create(success=True, **fields)
