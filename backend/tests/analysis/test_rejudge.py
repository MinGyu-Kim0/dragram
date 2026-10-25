"""후보가 늘어난 기존 구간을 조회할 때 다시 판정하기(#176).

용법 완결이 아닌 패턴에 새 용법이 더해지면 패턴 세트 버전은 오르지 않는다. 캐시 문장을 조회할 때
저장된 후보에 없던 용법이 지금 후보에 있는 구간만 재매칭 재판정(#114)과 같은 길로 다시 판정한다.
"""

import pytest
from django.db import transaction

from analysis import patterns
from analysis.models import GrammarPattern, SentenceAnalysis, SpanMatch
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, connected_client, new_usage, post, span_answer
from tests.analysis.test_divergent import alternative, divergent
from tests.analysis.test_limits import spend
from tests.analysis.test_rematch import GA, KITEIRU, TEIRU, register, version
from tests.analysis.test_rematch_worker import holder_calls  # noqa: F401
from tests.analysis.test_usage_rules import TOKYO_DE, register_de, rule
from tests.analysis.test_worker import _read_in_thread, _stored_values, _wait_until, _work_burst

pytestmark = pytest.mark.django_db


def add_teiru_usage(name):
    pattern = GrammarPattern.objects.get(name="ている")
    with transaction.atomic():
        usage, _ = patterns.add_usage(pattern, name, f"{name}을 나타낸다", None)
    return usage


def cache_teiru(client, fake_llm, *more_usages):
    """ている(진행과 more_usages)를 등록하고 KITEIRU를 진행으로 캐시한다."""
    register(fake_llm, "走っている", TEIRU)
    for name in more_usages:
        add_teiru_usage(name)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, KITEIRU)
    fake_llm.forget_requests()


def stored_span():
    return SentenceAnalysis.objects.get(translation_ko="그가 와 있다").span_matches.get(
        pattern__name="ている"
    )


def names(response):
    return [item["name"] for item in response.json()["grammar"]]


def test_decided_span_whose_candidates_grew_is_checked_then_saved_with_the_new_usage(
    client, fake_llm
):
    cache_teiru(client, fake_llm)
    before = version()
    result = add_teiru_usage("결과 상태")
    assert version() == before
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "analysis"]
    early = response.events[0]
    # 옛 판정은 확정 목록에서 빠지고 '확인 중'으로 온다.
    assert early["grammar"] == []
    assert [[c["name"] for c in item["candidates"]] for item in early["checking"]] == [
        ["진행", "결과 상태"]
    ]
    assert names(response) == ["결과 상태"]
    [request] = fake_llm.rematch_requests
    assert [span["start_token_id"] for span in request["spans"]] == [3]
    assert request["translation_ko"] == "그가 와 있다"
    span = stored_span()
    assert (span.state, span.usage_id) == (SpanMatch.State.DECIDED, result.id)
    assert {c["usage_id"] for c in span.candidates} == {result.id, span.candidates[0]["usage_id"]}
    assert len(span.candidates) == 2

    # 다시 판정한 뒤에는 후보가 그대로라 LLM 없이 한 번에 온다.
    fake_llm.forget_requests()
    again = analyze(client, KITEIRU)
    assert again.types() == ["translation", "analysis"]
    assert names(again) == ["결과 상태"]
    assert fake_llm.all_requests() == []


def test_span_whose_candidates_did_not_grow_is_not_asked(client, fake_llm):
    register(fake_llm, "走っている", TEIRU)
    register(fake_llm, "雨が降る", GA)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "usage", 1), span_answer(1, "usage", 2)],
    }
    analyze(client, KITEIRU)
    fake_llm.forget_requests()
    add_teiru_usage("결과 상태")
    # 후보 ID: ている 1·2(진행, 결과 상태), が 3(주격)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}

    response = analyze(client, KITEIRU)

    [request] = fake_llm.rematch_requests
    assert [span["start_token_id"] for span in request["spans"]] == [3]
    # 다시 판정하지 않는 が는 정해진 구간으로 알린다.
    assert [span["name"] for span in request["decided_spans"]] == ["주격"]
    assert response.events[0]["grammar"][0]["name"] == "주격"
    assert names(response) == ["주격", "결과 상태"]


def test_span_decided_by_a_rule_is_not_asked_when_candidates_grow(client, fake_llm):
    pattern = register_de(client, fake_llm, "장소")
    rule(pattern, "장소")
    fake_llm.response = {"translation_ko": "도쿄에서 만난다"}
    analyze(client, TOKYO_DE)
    with transaction.atomic():
        patterns.add_usage(pattern, "원인", "원인을 나타낸다", None)
    fake_llm.forget_requests()

    response = analyze(client, TOKYO_DE)

    assert response.types() == ["translation", "analysis"]
    assert names(response) == ["장소"]
    assert fake_llm.all_requests() == []


def test_unfound_span_whose_own_new_usage_is_the_only_growth_is_not_asked(client, fake_llm):
    register(fake_llm, "走っている", TEIRU)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "unfound", new_usage=new_usage("결과 상태", "결과를 나타낸다"))],
    }
    analyze(client, KITEIRU)
    assert stored_span().usage.name == "결과 상태"
    fake_llm.forget_requests()

    response = analyze(client, KITEIRU)

    assert response.types() == ["translation", "analysis"]
    assert fake_llm.all_requests() == []


@pytest.mark.parametrize(
    "state",
    [SpanMatch.State.NOT_APPLICABLE, SpanMatch.State.DIVERGENT, SpanMatch.State.UNRESOLVED],
)
def test_not_applicable_divergent_and_unresolved_spans_are_judged_again(client, fake_llm, state):
    cache_teiru(client, fake_llm, "결과 상태")
    span = stored_span()
    other = span.candidates[1]["usage_id"]
    SpanMatch.objects.filter(pk=span.pk).update(
        state=state,
        usage=span.usage if state == SpanMatch.State.DIVERGENT else None,
        alternatives=(
            [{"usage_id": other, "translation_ko": "그가 와 있는 상태다"}]
            if state == SpanMatch.State.DIVERGENT
            else None
        ),
    )
    done = add_teiru_usage("완료")
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 3)]}

    response = analyze(client, KITEIRU)

    assert len(fake_llm.rematch_requests) == 1
    assert names(response) == ["완료"]
    span = stored_span()
    assert (span.state, span.usage_id, span.alternatives) == (
        SpanMatch.State.DECIDED,
        done.id,
        None,
    )


def test_divergent_answer_saves_the_alternative_and_its_translation(client, fake_llm):
    cache_teiru(client, fake_llm)
    add_teiru_usage("결과 상태")
    fake_llm.rematch_response = {"spans": [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))]}

    response = analyze(client, KITEIRU)

    [item] = response.json()["grammar"]
    assert item["name"] == "진행"
    assert [(a["name"], a["translation_ko"]) for a in item["alternatives"]] == [
        ("결과 상태", "그가 와 있는 상태다")
    ]
    assert stored_span().state == SpanMatch.State.DIVERGENT


def test_new_span_and_grown_span_are_judged_in_one_request(client, fake_llm):
    cache_teiru(client, fake_llm)
    register(fake_llm, "雨が降る", GA)
    add_teiru_usage("결과 상태")
    fake_llm.forget_requests()
    # 후보 ID: ている 1·2(진행, 결과 상태), が 3(주격)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 3), span_answer(1, "usage", 2)]}

    response = analyze(client, KITEIRU)

    [request] = fake_llm.rematch_requests
    assert [span["start_token_id"] for span in request["spans"]] == [1, 3]
    assert names(response) == ["주격", "결과 상태"]


def test_failed_judge_keeps_the_stored_result_and_is_retried(client, fake_llm):
    cache_teiru(client, fake_llm)
    add_teiru_usage("결과 상태")
    fake_llm.rematch_error = BusinessError(AnalysisError.FAILED, "LLM 재판정 호출 실패")

    response = analyze(client, KITEIRU)

    assert "error" not in response.json()
    assert names(response) == ["진행"]
    assert stored_span().usage.name == "진행"
    fake_llm.rematch_error = None
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}
    assert names(analyze(client, KITEIRU)) == ["결과 상태"]


def test_over_the_limit_sends_the_stored_result_without_judging(
    settings, client, fake_llm, analyst
):
    cache_teiru(client, fake_llm)
    add_teiru_usage("결과 상태")
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 100
    spend(analyst, 60, 40)

    response = analyze(client, KITEIRU)

    assert response.types() == ["translation", "analysis"]
    assert names(response) == ["진행"]
    assert fake_llm.all_requests() == []


def test_candidates_changing_again_before_saving_saves_nothing(client, fake_llm):
    cache_teiru(client, fake_llm)
    add_teiru_usage("결과 상태")
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}
    fake_llm.before_rematch = lambda: add_teiru_usage("완료")

    response = analyze(client, KITEIRU)

    assert names(response) == ["진행"]
    assert stored_span().usage.name == "진행"
    # 다음 조회가 늘어난 후보 셋으로 다시 판정한다.
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 3)]}
    assert names(analyze(client, KITEIRU)) == ["완료"]
    assert len(fake_llm.rematch_requests[-1]["spans"][0]["candidates"]) == 3


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_same_sentence_at_once_judges_grown_spans_once(
    settings,
    fake_llm,
    redis_db,
    holder_calls,  # noqa: F811
):
    cache_teiru(connected_client(), fake_llm)
    add_teiru_usage("결과 상태")
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}
    settings.ANALYSIS_INLINE = False
    results = []

    first = _read_in_thread(post(connected_client(), KITEIRU), results)
    _wait_until(lambda: redis_db.keys("rematch:*"))
    second = _read_in_thread(post(connected_client(), KITEIRU), results)
    _wait_until(lambda: holder_calls)
    _work_burst()
    first.join(10)
    second.join(10)

    assert len(fake_llm.rematch_requests) == 1
    assert [r.types() for r in results] == [["grammar", "translation", "analysis"]] * 2
    assert [names(r) for r in results] == [["결과 상태"]] * 2
    assert not redis_db.keys("rematch:*")
    # 큐 입력·잠금·소식 어디에도 원문이 남지 않는다.
    assert all("来".encode() not in value for value in _stored_values(redis_db))
