"""고정 평가 세트로 분석 품질 재기(#177). 이음새는 관리 명령 evaluate와 admin 채점 화면이다."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connections
from django.db.models import F

from analysis import evaluation
from analysis.evaluation import metrics
from analysis.management.commands import evaluate as evaluate_command
from analysis.models import (
    EvalItem,
    EvalResult,
    EvalRun,
    EvalSentence,
    SentenceAnalysis,
    UsageLog,
)
from tests.analysis.helpers import analyze, saved_analyses, span_answer
from tests.analysis.test_parts import TABETESHIMATTA, TESHIMAT, TESHIMAU

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
HASHITTEIRU = "走っている"


def evaluate(*args):
    out = StringIO()
    call_command("evaluate", *args, stdout=out, stderr=out)
    return out.getvalue()


def new_pattern_response(fake_llm):
    """走っている의 ている를 새 구문으로 등록하는 첫 응답."""
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [
            {
                "tokens": [{"token_id": 1, "fix": "lemma"}, {"token_id": 2, "fix": "lemma"}],
                "pattern_name": "ている",
                "usage_name": "진행",
                "explanation_ko": "동작이 이어지고 있음을 나타낸다",
                "example_ja": "雨が降っている",
                "korean_equivalent": "~고 있다",
                "function_tags": [],
            }
        ],
    }


def test_run_records_each_sentence_translation_items_and_calls(fake_llm, redis_db):
    sentence = EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    new_pattern_response(fake_llm)

    evaluate("--yes")

    run = EvalRun.objects.get()
    assert run.status == EvalRun.Status.COMPLETE
    result = run.results.get()
    assert result.sentence == sentence
    assert result.failed is False
    assert result.translation_ko == "달리고 있다"
    assert result.calls == 1
    assert (result.input_tokens, result.output_tokens) == (100, 10)
    item = result.items.get()
    assert (item.start, item.end, item.surface) == (2, 5, "ている")
    assert (item.state, item.pattern_name, item.name) == ("decided", "ている", "진행")
    # 실행 결과에서 그 문장의 사용 기록(request 행)으로 거꾸로 찾아간다.
    assert result.usage_request.path == UsageLog.Path.LLM
    assert item.grade == EvalItem.Grade.UNGRADED
    # 사용 기록에는 사용자 없이 남아 누구의 하루 한도에도 들지 않는다.
    assert not UsageLog.objects.filter(user__isnull=False).exists()


def test_daily_limit_does_not_apply_to_runs_without_user(fake_llm, redis_db, settings):
    # 채우기 명령 같은 다른 관리 작업도 user 없이 남는다. 모두 합쳐 한도를 넘어도 평가는 돈다.
    UsageLog.objects.create(
        kind=UsageLog.Kind.LLM, purpose="usage_fill", input_tokens=10**6, success=True
    )
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1000
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    new_pattern_response(fake_llm)

    evaluate("--yes")

    assert EvalResult.objects.get().failed is False


def test_without_yes_reports_count_and_calls_nothing(fake_llm, redis_db):
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")

    out = evaluate()

    assert "평가 문장 1개" in out
    assert fake_llm.all_requests() == []
    assert not EvalRun.objects.exists()


def test_cached_sentence_is_analyzed_again_and_inactive_sentences_are_skipped(
    fake_llm, redis_db, client
):
    new_pattern_response(fake_llm)
    analyze(client, HASHITTEIRU)
    fake_llm.forget_requests()
    # 이제 ている 패턴이 있어 그 구간을 후보로 묻는다.
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": [span_answer(0, candidate_id=1)]}
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    EvalSentence.objects.create(text="雨が降る", category="normal", is_active=False)

    evaluate("--yes")

    assert len(fake_llm.requests) == 1
    result = EvalResult.objects.get()
    assert result.calls == 1
    assert result.items.get().name == "진행"
    # 평가 뒤에도 사용자 캐시는 쓸 수 있다.
    assert saved_analyses().get().is_stale is False


def test_one_failed_sentence_does_not_stop_the_rest(fake_llm, redis_db):
    broken = EvalSentence.objects.create(text="   ", category="no_grammar")
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    new_pattern_response(fake_llm)

    evaluate("--yes")

    run = EvalRun.objects.get()
    assert run.status == EvalRun.Status.COMPLETE
    failed, ok = run.results.order_by("sentence_id")
    assert (failed.sentence, failed.failed) == (broken, True)
    assert ok.failed is False


def run_twice(fake_llm, between=None):
    """같은 결과가 나오는 실행 두 번. 첫 실행의 항목을 맞다로 채점해 둔다."""
    new_pattern_response(fake_llm)
    evaluate("--yes")
    EvalItem.objects.update(grade=EvalItem.Grade.CORRECT)
    if between:
        between()
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": [span_answer(0, candidate_id=1)]}
    evaluate("--yes")
    return EvalRun.objects.order_by("id").last().results.get().items.get()


def test_same_result_carries_over_the_last_grade(fake_llm, redis_db):
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")

    assert run_twice(fake_llm).grade == EvalItem.Grade.CORRECT


def test_edited_sentence_does_not_carry_over_grades(fake_llm, redis_db):
    sentence = EvalSentence.objects.create(text=HASHITTEIRU, category="normal")

    def edit():
        sentence.text = f" {HASHITTEIRU}"
        sentence.save()

    assert run_twice(fake_llm, edit).grade == EvalItem.Grade.UNGRADED


def test_different_result_is_left_ungraded(fake_llm, redis_db):
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")

    def other_usage_last_time():
        EvalItem.objects.update(usage_ref=None)

    assert run_twice(fake_llm, other_usage_last_time).grade == EvalItem.Grade.UNGRADED


def graded_run():
    """채점을 마친 실행. 손으로 계산한 지표와 비교한다."""
    run = EvalRun.objects.create(status=EvalRun.Status.COMPLETE)
    sentence = EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    result = EvalResult.objects.create(
        run=run,
        sentence=sentence,
        text=HASHITTEIRU,
        missed=1,
        calls=2,
        input_tokens=300,
        cached_input_tokens=100,
        output_tokens=30,
    )
    for state, grade in [
        ("decided", "correct"),
        ("decided", "ambiguous"),
        ("divergent", "wrong_usage"),
        ("decided", "wrong_span"),
        ("unresolved", "ungraded"),
    ]:
        EvalItem.objects.create(
            result=result,
            start=0,
            end=1,
            surface="走",
            pattern_name="패턴",
            pattern_ref=1,
            state=state,
            name="이름",
            review_status="pending",
            grade=grade,
        )
    EvalResult.objects.create(
        run=run,
        sentence=sentence,
        text=HASHITTEIRU,
        failed=True,
        calls=1,
        input_tokens=100,
        output_tokens=10,
    )
    return run


def test_metrics_follow_the_grades(settings):
    settings.EVAL_PRICE_INPUT = 1.0
    settings.EVAL_PRICE_CACHED_INPUT = 0.5
    settings.EVAL_PRICE_OUTPUT = 4.0

    m = metrics(graded_run())

    assert (m["sentences"], m["failed"], m["items"], m["ungraded"]) == (2, 1, 5, 1)
    # 실패한 문장은 놓친 문법을 적을 필요가 없다.
    assert m["missed_unchecked"] == 0
    # 구간이 맞은 3 ÷ (채점한 4 + 놓친 1)
    assert m["span_accuracy"] == pytest.approx(0.6)
    # 맞다 1 ÷ 구간이 맞은 3, 애매 1 ÷ 3
    assert m["usage_accuracy"] == pytest.approx(1 / 3)
    assert m["ambiguous_rate"] == pytest.approx(1 / 3)
    # 미확정 1 ÷ 항목 5
    assert m["unresolved_rate"] == pytest.approx(0.2)
    assert m["calls_per_sentence"] == pytest.approx(1.5)
    assert (m["input_tokens"], m["cached_input_tokens"], m["output_tokens"]) == (400, 100, 40)
    # (캐시 아닌 입력 300 × 1 + 캐시 입력 100 × 0.5 + 출력 40 × 4) ÷ 100만
    assert m["cost_usd"] == pytest.approx(0.00051)


def test_cost_is_empty_without_prices(settings):
    settings.EVAL_PRICE_INPUT = None

    assert metrics(graded_run())["cost_usd"] is None


def test_rates_are_empty_before_grading():
    run = EvalRun.objects.create()

    m = metrics(run)

    assert m["span_accuracy"] is None
    assert m["usage_accuracy"] is None
    assert m["unresolved_rate"] is None


RESULTS = "/admin/analysis/evalresult/"
RUNS = "/admin/analysis/evalrun/"


def test_admin_grades_items_and_missed_count_only(admin_client):
    run = graded_run()
    result = run.results.get(failed=False)
    items = list(result.items.order_by("id"))
    data = {
        "missed": "2",
        # 바꿀 수 없는 칸은 보내도 무시된다.
        "translation_ko": "바꾼 번역",
        "items-TOTAL_FORMS": len(items),
        "items-INITIAL_FORMS": len(items),
        "items-MIN_NUM_FORMS": "0",
        "items-MAX_NUM_FORMS": "1000",
    }
    for i, item in enumerate(items):
        data |= {
            f"items-{i}-id": item.pk,
            f"items-{i}-result": result.pk,
            f"items-{i}-grade": "correct",
            f"items-{i}-name": "바꾼 이름",
        }

    response = admin_client.post(f"{RESULTS}{result.pk}/change/", data)

    assert response.status_code == 302
    result.refresh_from_db()
    assert (result.missed, result.translation_ko) == (2, None)
    assert set(result.items.values_list("grade", "name")) == {("correct", "이름")}


def test_admin_run_list_shows_metrics_side_by_side(admin_client):
    graded_run()
    EvalRun.objects.create(status=EvalRun.Status.COMPLETE)

    page = admin_client.get(RUNS).content.decode()

    # 구간 정확도 60%, 용법 정확도 33.3%, 미채점 1
    assert "60.0%" in page
    assert "33.3%" in page


def test_admin_cannot_add_runs_results_or_items(admin_client):
    assert admin_client.get(f"{RUNS}add/").status_code == 403
    assert admin_client.get(f"{RESULTS}add/").status_code == 403


def test_failed_run_keeps_the_cached_analysis_usable(fake_llm, redis_db, client):
    new_pattern_response(fake_llm)
    analyze(client, HASHITTEIRU)
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": "틀린 답"}

    evaluate("--yes")

    assert EvalResult.objects.get().failed is True
    cached = saved_analyses().get()
    assert (cached.status, cached.is_stale) == ("complete", False)
    assert cached.translation_ko == "달리고 있다"


def test_same_range_items_of_different_patterns_keep_their_own_pattern(fake_llm, redis_db):
    EvalSentence.objects.create(text=TABETESHIMATTA, category="normal")
    fake_llm.response = {
        "translation_ko": "먹어 버렸다",
        "new_patterns": [TESHIMAU, {**TESHIMAT, "usage_name": "완료"}],
    }

    evaluate("--yes")

    items = EvalResult.objects.get().items.order_by("id")
    assert {(i.name, i.pattern_name) for i in items} == {("완료", "てしまう"), ("완료", "てしまっ")}
    assert len({i.pattern_ref for i in items}) == 2


def test_missed_count_carries_over_only_with_the_same_items(fake_llm, redis_db):
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")

    def missed_one():
        EvalResult.objects.update(missed=1)

    run_twice(fake_llm, missed_one)

    assert EvalRun.objects.order_by("id").last().results.get().missed == 1


def test_missed_count_is_unchecked_when_items_differ(fake_llm, redis_db):
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")

    def different_last_time():
        EvalResult.objects.update(missed=1)
        EvalItem.objects.update(usage_ref=None)

    run_twice(fake_llm, different_last_time)

    run = EvalRun.objects.order_by("id").last()
    assert run.results.get().missed is None
    assert metrics(run)["missed_unchecked"] == 1


def test_failed_run_does_not_revive_a_cache_made_stale_before_the_claim(
    fake_llm, redis_db, client, monkeypatch
):
    new_pattern_response(fake_llm)
    analyze(client, HASHITTEIRU)
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    fake_llm.response = {"translation_ko": "달리고 있다", "spans": "틀린 답"}
    take = evaluation.take

    def rejected_in_between(sentence, again=False):
        # 평가가 캐시를 읽은 뒤 선점하기 전에 관리자가 반려해 무효화한 경우
        SentenceAnalysis.objects.update(is_stale=True, generation=F("generation") + 1)
        return take(sentence, again)

    monkeypatch.setattr(evaluation, "take", rejected_in_between)

    evaluate("--yes")

    assert saved_analyses().get().is_stale is True


def test_second_run_waits_for_the_first_to_finish(fake_llm, redis_db):
    EvalSentence.objects.create(text=HASHITTEIRU, category="normal")
    other = connections.create_connection("default")
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [evaluate_command.LOCK_KEY])

        out = evaluate("--yes")
    finally:
        other.close()

    assert "진행 중" in out
    assert fake_llm.all_requests() == []
    assert not EvalRun.objects.exists()
