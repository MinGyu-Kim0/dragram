"""패턴 세트 버전이 오른 뒤 캐시 문장을 다시 매칭하기(#41)."""

import threading
from unittest.mock import ANY

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import F

from analysis import jobs, patterns, review
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    PatternSetVersion,
    SentenceAnalysis,
    SpanMatch,
    UsageLog,
)
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import (
    analyze,
    connected_client,
    new_pattern,
    new_usage,
    span_answer,
    wait_until_blocked,
)

pytestmark = pytest.mark.django_db

# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"
# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))
# 토큰: 0 雨 / 1 が / 2 降る
GA = new_pattern(
    (1, "lemma"),
    pattern_name="が",
    usage_name="주격",
    explanation_ko="동작이나 상태의 주체를 나타낸다",
    example_ja="猫が鳴く",
)


def register(fake_llm, sentence, proposal, translation="번역"):
    """다른 문장을 분석해 새 패턴을 등록·활성화한다(패턴 세트 버전이 1 오른다)."""
    mine = fake_llm.response
    fake_llm.response = {"translation_ko": translation, "new_patterns": [proposal]}
    analyze(connected_client(), sentence)
    fake_llm.response = mine


def version():
    return PatternSetVersion.objects.get().version


def stored(sentence_text=KITEIRU):
    return SentenceAnalysis.objects.latest("id")


def test_analysis_records_the_pattern_set_version_read_before_matching(client, fake_llm):
    register(fake_llm, "走っている", TEIRU)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}
    # LLM을 기다리는 사이 다른 패턴이 활성화된다.
    fake_llm.before_respond = lambda: register(fake_llm, "雨が降る", GA)

    analyze(client, KITEIRU)

    assert version() == 2
    assert stored().matcher_version == 1
    # 그사이 활성화된 が는 다음 조회가 다시 매칭해 찾는다(후보 ID는 ている 다음이라 2).
    fake_llm.forget_requests()
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}
    analyze(client, KITEIRU)
    [request] = fake_llm.rematch_requests
    assert [span["start_token_id"] for span in request["spans"]] == [1]


def test_stale_analysis_replaced_records_the_version_read_before_matching(client, fake_llm):
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, KITEIRU)
    register(fake_llm, "走っている", TEIRU)
    SentenceAnalysis.objects.filter(translation_ko="그가 와 있다").update(is_stale=True)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    analyze(client, KITEIRU)

    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert (analysis.is_stale, analysis.matcher_version) == (False, 1)


def test_same_span_cannot_be_stored_twice(client, fake_llm):
    register(fake_llm, "走っている", TEIRU)
    span = SpanMatch.objects.get()
    span.pk = None

    with pytest.raises(IntegrityError), transaction.atomic():
        span.save()


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_stale_replacement_conflicting_on_the_same_span_saves_nothing(fake_llm):
    register(fake_llm, "走っている", TEIRU)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}
    analyze(connected_client(), KITEIRU)
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    SentenceAnalysis.objects.filter(pk=analysis.pk).update(is_stale=True)
    fake_llm.response = {"translation_ko": "늦게 끝난 번역", "spans": [span_answer(0, "usage", 1)]}
    result = {}

    def reanalysis():
        try:
            result["response"] = analyze(connected_client(), KITEIRU)
        finally:
            connection.close()

    # 분석 행을 잠그지 않은 쓰기가 같은 구간을 넣고 아직 커밋하지 않았다. 다시 분석하는 요청은
    # 분석 행을 잠근 뒤 옛 구간을 지우려다 기다린다.
    thread = threading.Thread(target=reanalysis)
    with transaction.atomic():
        span = analysis.span_matches.get()
        analysis.span_matches.all().delete()
        span.pk = None
        span.save()
        thread.start()
        wait_until_blocked()
    thread.join()

    # 같은 구간이 먼저 들어가 저장하지 못했다. 덮어쓰지 않고 실패로 알려 다음 요청이 다시 분석한다.
    assert result["response"].json() == {"error": "ANALYSIS:FAILED"}
    analysis.refresh_from_db()
    assert (analysis.translation_ko, analysis.status) == ("그가 와 있다", "failed")
    # 저장하지 못한 요청은 성공으로 남지 않는다.
    assert not UsageLog.objects.filter(kind=UsageLog.Kind.REQUEST).latest("id").success
    assert analysis.span_matches.count() == 1


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_rematch_conflicting_on_the_same_span_saves_nothing_and_falls_back(fake_llm):
    cache_then_register_teiru(connected_client(), fake_llm)
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    usage = GrammarUsage.objects.get(name="진행")
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    result = {}

    def rematch():
        try:
            result["response"] = analyze(connected_client(), KITEIRU)
        finally:
            connection.close()

    # 분석 행을 잠그지 않은 쓰기가 같은 구간을 넣고 아직 커밋하지 않았다. 재매칭은 행을 잠그고
    # 열쇠를 확인한 뒤 같은 구간을 넣으려다 기다린다.
    thread = threading.Thread(target=rematch)
    with transaction.atomic():
        SpanMatch.objects.create(
            analysis=analysis,
            pattern=usage.pattern,
            usage=usage,
            start_offset=3,
            end_offset=6,
            state="decided",
            decided_by="llm",
        )
        thread.start()
        wait_until_blocked()
    thread.join()

    response = result["response"]
    assert response.types() == ["grammar", "translation", "analysis"]
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    analysis.refresh_from_db()
    assert (analysis.matcher_version, analysis.span_matches.count()) == (0, 1)


def teiru_without_usages(fake_llm):
    """하나뿐인 용법이 반려돼 매칭 자격이 없는(활성이지만 용법 0개) ている."""
    register(fake_llm, "走っている", TEIRU)
    pattern = GrammarPattern.objects.get(name="ている")
    usage = pattern.usages.get()
    review.reject_usage(usage)
    return pattern, usage


def test_unrejecting_the_only_usage_raises_the_version(client, fake_llm):
    _, usage = teiru_without_usages(fake_llm)
    before = version()

    review.unreject_usage(usage)

    assert version() == before + 1


def test_unrejecting_another_usage_does_not_raise_the_version(client, fake_llm):
    register(fake_llm, "走っている", TEIRU)
    pattern = GrammarPattern.objects.get()
    with transaction.atomic():
        second, _ = patterns.add_usage(pattern, "결과 상태", "결과가 남아 있다", None)
    review.reject_usage(second)
    before = version()

    review.unreject_usage(second)

    assert version() == before


def test_first_usage_added_by_asking_again_raises_the_version(client, fake_llm):
    teiru_without_usages(fake_llm)
    before = version()
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과 상태")],
    }
    fake_llm.rejudge_response = {
        "spans": [
            span_answer(
                0,
                "unfound",
                new_usage=new_usage("결과 상태", "동작의 결과가 남아 있다", "窓が開いている"),
            )
        ]
    }

    analyze(client, KITEIRU)

    assert GrammarUsage.objects.filter(name="결과 상태").exists()
    assert version() == before + 1


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_first_usage_raises_the_version_before_locking_the_analysis(fake_llm):
    # 彼が来ている의 が 구간이 저장된 stale 분석. ている는 용법이 0개다.
    teiru_without_usages(fake_llm)
    register(fake_llm, "雨が降る", GA)
    ga = GrammarPattern.objects.get(name="が")
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}
    analyze(connected_client(), KITEIRU)
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    SentenceAnalysis.objects.filter(pk=analysis.pk).update(is_stale=True)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "usage", 1)],
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과 상태")],
    }
    fake_llm.rejudge_response = {
        "spans": [
            span_answer(
                0, "unfound", new_usage=new_usage("결과 상태", "결과가 남아 있다", "窓が開いている")
            )
        ]
    }
    result = {}

    def reanalysis():
        try:
            result["response"] = analyze(connected_client(), KITEIRU)
        finally:
            connection.close()

    # 관리자 전이가 패턴 → 버전을 잠근 채, 다시 분석하는 요청이 ている에 첫 용법을 붙이고 버전을
    # 기다린다. 그 뒤 전이가 분석 행을 잠근다. 분석 요청이 분석 행을 먼저 잠갔다면 교착이다.
    thread = threading.Thread(target=reanalysis)
    with transaction.atomic():
        GrammarPattern.objects.select_for_update(no_key=True).get(pk=ga.pk)
        patterns.raise_pattern_set_version()
        thread.start()
        wait_until_blocked()
        patterns.make_stale(pattern=ga)
    thread.join()

    # 교착 없이 끝났다. 분석하는 사이 전이가 세대 번호를 올려 저장하지 않고 실패로 알린다(#98).
    assert result["response"].json() == {"error": "ANALYSIS:FAILED"}


def test_rematch_without_new_spans_only_raises_the_matcher_version(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다"}
    analyze(client, "走っている")
    register(fake_llm, "雨が降る", GA)
    fake_llm.forget_requests()

    response = analyze(client, "走っている")

    assert fake_llm.all_requests() == []
    assert response.types() == ["translation", "analysis"]
    assert response.json()["translation_ko"] == "달리고 있다"
    analysis = SentenceAnalysis.objects.get(translation_ko="달리고 있다")
    assert analysis.matcher_version == version() == 1


def test_span_of_the_pattern_registered_by_the_sentence_is_not_judged_again(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}
    analyze(client, "走っている")
    fake_llm.forget_requests()

    response = analyze(client, "走っている")

    assert fake_llm.all_requests() == []
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    assert SentenceAnalysis.objects.get().matcher_version == 1


@pytest.mark.parametrize(
    "answer",
    [
        span_answer(0, "not_applicable"),
        # 이미 있는 이름이라 더하지 못한 새 용법: 패턴이 있는 미발견 구간으로 남는다.
        span_answer(0, "unfound", new_usage=new_usage("진행", "진행", "窓が開いている")),
    ],
)
def test_stored_not_applicable_or_unfound_span_is_not_judged_again(client, fake_llm, answer):
    register(fake_llm, "走っている", TEIRU)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [answer]}
    analyze(client, KITEIRU)
    with transaction.atomic():
        patterns.raise_pattern_set_version()
    fake_llm.forget_requests()

    analyze(client, KITEIRU)

    assert fake_llm.all_requests() == []
    assert SentenceAnalysis.objects.get(translation_ko="그가 와 있다").matcher_version == 2


def closed_teiru(fake_llm):
    """승인된 용법 하나만 가진, 승인된 용법 완결 ている 패턴."""
    register(fake_llm, "走っている", TEIRU)
    pattern = GrammarPattern.objects.get(name="ている")
    review.update_test_cases(
        pattern,
        [
            {"text": "雨が降っている", "should_match": True},
            {"text": "雨が降る", "should_match": False},
        ],
    )
    review.approve_pattern(pattern)
    review.approve_usage(pattern.usages.get())
    review.close_usages(pattern)
    return pattern


def test_new_span_of_a_usage_closed_pattern_is_saved_without_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, KITEIRU)
    closed_teiru(fake_llm)
    fake_llm.forget_requests()

    response = analyze(client, KITEIRU)

    assert fake_llm.all_requests() == []
    assert response.types() == ["translation", "analysis"]
    assert response.json()["grammar"] == [
        {
            "start": 3,
            "end": 6,
            "state": "decided",
            "connection": ANY,
            "pattern_name": "ている",
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "pos_tags": ["particle", "verb"],
            "function_tags": [],
            "function_tags_review_status": None,
            "review_status": "approved",
            "register": "standard",
            "variant_of": None,
        }
    ]
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    span = analysis.span_matches.get()
    assert (span.state, span.decided_by) == ("decided", "single_usage")
    assert analysis.matcher_version == version()


def cache_then_register_teiru(client, fake_llm, sentence=KITEIRU, translation="그가 와 있다"):
    """패턴이 없을 때 문장을 캐시하고, 그 뒤 미검수 ている를 등록한다(판별 대상 새 구간)."""
    fake_llm.response = {"translation_ko": translation}
    analyze(client, sentence)
    register(fake_llm, "走っている", TEIRU)
    fake_llm.forget_requests()


def test_new_span_after_a_pattern_is_activated_is_judged_once_and_saved(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "analysis"]
    first = response.events[0]
    assert (first["type"], first["grammar"]) == ("grammar", [])
    [checking] = first["checking"]
    assert (checking["start"], checking["end"]) == (3, 6)
    assert checking["candidates"] == [{"name": "진행", "review_status": "pending"}]
    assert checking["usage"]["name"] == "진행"
    assert response.events[1]["translation_ko"] == "그가 와 있다"
    [request] = fake_llm.rematch_requests
    assert request["translation_ko"] == "그가 와 있다"
    assert request["decided_spans"] == []
    assert request["spans"] == [
        {
            "span_id": 0,
            "start_token_id": 3,
            "end_token_id": 4,
            "candidates": [
                {
                    "candidate_id": 1,
                    "name": "진행",
                    "explanation_ko": "동작이 이어지고 있음을 나타낸다",
                }
            ],
        }
    ]
    assert fake_llm.all_requests() == [request]
    assert response.json()["translation_ko"] == "그가 와 있다"
    assert response.json()["grammar"] == [
        {
            "start": 3,
            "end": 6,
            "state": "decided",
            "connection": ANY,
            "pattern_name": "ている",
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "pos_tags": ["particle", "verb"],
            "function_tags": [],
            "function_tags_review_status": None,
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
        }
    ]
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert analysis.matcher_version == version()
    assert not analysis.is_stale


def test_cached_sentences_nobody_views_again_are_not_judged(client, fake_llm):
    fake_llm.response = {"translation_ko": "그녀가 와 있다"}
    analyze(client, "彼女が来ている")
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}

    analyze(client, KITEIRU)

    # 다시 조회한 문장만 재판정한다.
    [request] = fake_llm.all_requests()
    assert request["translation_ko"] == "그가 와 있다"
    unviewed = SentenceAnalysis.objects.get(translation_ko="그녀가 와 있다")
    assert not unviewed.span_matches.exists()


def test_cached_sentence_is_matched_again_when_an_inactive_pattern_is_activated(client, fake_llm):
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, KITEIRU)
    # 예문이 걸리지 않아 비활성으로 등록된다.
    register(fake_llm, "走っている", {**TEIRU, "example_ja": "雨が降る"})
    pattern = GrammarPattern.objects.get()
    assert not pattern.is_active
    fake_llm.forget_requests()
    analyze(client, KITEIRU)
    assert fake_llm.all_requests() == []
    before = version()

    review.update_test_cases(
        pattern,
        [
            {"text": "雨が降っている", "should_match": True},
            {"text": "雨が降る", "should_match": False},
        ],
    )

    pattern.refresh_from_db()
    assert pattern.is_active
    assert version() == before + 1
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    response = analyze(client, KITEIRU)
    assert len(fake_llm.rematch_requests) == 1
    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]


def test_other_place_of_the_pattern_registered_by_the_sentence_is_judged(client, fake_llm):
    # 토큰: 0 見 / 1 て / 2 いる / 3 人 / 4 が / 5 来 / 6 て / 7 いる
    fake_llm.response = {
        "translation_ko": "보고 있는 사람이 와 있다",
        "new_patterns": [new_pattern((1, "lemma"), (2, "lemma"))],
    }
    analyze(client, "見ている人が来ている")
    fake_llm.forget_requests()
    # 후보 ID는 매칭된 구간 전체에 이어 매기므로 둘째 자리의 진행은 2다.
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}

    response = analyze(client, "見ている人が来ている")

    [request] = fake_llm.rematch_requests
    assert [span["start_token_id"] for span in request["spans"]] == [6]
    assert request["decided_spans"] == [{"start_token_id": 1, "end_token_id": 2, "name": "진행"}]
    assert [item["start"] for item in response.json()["grammar"]] == [1, 7]


def test_stored_and_new_decided_spans_are_told_to_the_judge(client, fake_llm):
    # が가 정해진 캐시 문장에 미검수 ている가 새로 걸린다.
    register(fake_llm, "雨が降る", GA)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}
    analyze(client, KITEIRU)
    register(fake_llm, "走っている", TEIRU)
    fake_llm.forget_requests()
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 2)]}

    analyze(client, KITEIRU)

    [request] = fake_llm.rematch_requests
    assert request["decided_spans"] == [{"start_token_id": 1, "end_token_id": 1, "name": "주격"}]
    assert [span["start_token_id"] for span in request["spans"]] == [3]


def test_rematch_judge_may_add_a_new_usage(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {
        "spans": [
            span_answer(
                0, "unfound", new_usage=new_usage("결과 상태", "결과가 남아 있다", "窓が開いている")
            )
        ]
    }

    response = analyze(client, KITEIRU)

    usage = GrammarUsage.objects.get(name="결과 상태")
    assert usage.example_ja == "窓が開いている"
    assert [item["name"] for item in response.json()["grammar"]] == ["결과 상태"]


def test_copied_example_of_a_rematch_usage_is_rewritten(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {
        "spans": [
            span_answer(
                0, "unfound", new_usage=new_usage("결과 상태", "결과가 남아 있다", "彼が来ている。")
            )
        ]
    }
    fake_llm.rewrite_response = {"examples": [{"example_id": 0, "example_ja": "窓が開いている"}]}

    analyze(client, KITEIRU)

    assert len(fake_llm.rewrite_requests) == 1
    assert GrammarUsage.objects.get(name="결과 상태").example_ja == "窓が開いている"


def test_rematch_judge_may_answer_divergent(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    pattern = GrammarPattern.objects.get(name="ている")
    with transaction.atomic():
        result, _ = patterns.add_usage(pattern, "결과 상태", "동작의 결과가 남아 있다", None)
    fake_llm.rematch_response = {
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
        ]
    }

    response = analyze(client, KITEIRU)

    span = SentenceAnalysis.objects.get(translation_ko="그가 와 있다").span_matches.get()
    assert span.state == "divergent"
    assert span.alternatives == [{"usage_id": result.id, "translation_ko": "그가 와 있는 상태다"}]
    assert response.json()["translation_ko"] == "그가 와 있다"


def rematch_starts(client, fake_llm, sentence):
    """그 문장을 조회했을 때 재판정에 보낸 새 구간의 시작 토큰들."""
    fake_llm.forget_requests()
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    analyze(client, sentence)
    return [
        span["start_token_id"] for request in fake_llm.rematch_requests for span in request["spans"]
    ]


def test_sentence_cached_while_a_pattern_had_no_usage_gets_its_span_after_unrejecting(
    client, fake_llm
):
    _, usage = teiru_without_usages(fake_llm)
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, KITEIRU)

    review.unreject_usage(usage)

    assert rematch_starts(client, fake_llm, KITEIRU) == [3]


def test_sentence_cached_while_a_pattern_had_no_usage_gets_its_span_after_a_first_usage(
    client, fake_llm
):
    teiru_without_usages(fake_llm)
    # 토큰: 0 雨 / 1 が / 2 降っ / 3 て / 4 いる
    fake_llm.response = {"translation_ko": "비가 오고 있다"}
    analyze(client, "雨が降っている")
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과 상태")],
    }
    fake_llm.rejudge_response = {
        "spans": [
            span_answer(
                0, "unfound", new_usage=new_usage("결과 상태", "결과가 남아 있다", "窓が開いている")
            )
        ]
    }
    analyze(client, KITEIRU)

    assert rematch_starts(client, fake_llm, "雨が降っている") == [3]


QUOTING_USAGE = new_usage("결과 상태", "彼が来ている의 결과", "窓が開いている")


@pytest.mark.parametrize(
    ("answers", "error"),
    [
        (None, BusinessError(AnalysisError.FAILED, "LLM 재판정 호출 실패")),
        ([span_answer(0, "usage", 9)], None),
        ([], None),
        ([span_answer(0, "unfound", new_usage=QUOTING_USAGE)], None),
    ],
)
def test_failed_rematch_judge_saves_nothing_and_is_retried_next_time(
    client, fake_llm, answers, error
):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {"spans": answers}
    fake_llm.rematch_error = error
    usages = GrammarUsage.objects.count()

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "analysis"]
    assert response.json()["translation_ko"] == "그가 와 있다"
    assert response.json()["grammar"] == []
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert (analysis.matcher_version, analysis.span_matches.count()) == (0, 0)
    assert GrammarUsage.objects.count() == usages
    fake_llm.rematch_error = None
    assert rematch_starts(client, fake_llm, KITEIRU) == [3]


def test_alternative_translation_same_as_the_stored_one_fails(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    pattern = GrammarPattern.objects.get(name="ている")
    with transaction.atomic():
        patterns.add_usage(pattern, "결과 상태", "동작의 결과가 남아 있다", None)
    fake_llm.rematch_response = {
        "spans": [
            {
                **span_answer(0, "divergent", 1),
                "alternatives": [
                    {"candidate_id": 2, "translation_ko": "그가 와 있다 ", "basis": "앞 문맥"}
                ],
            }
        ]
    }

    analyze(client, KITEIRU)

    assert not SpanMatch.objects.filter(analysis__translation_ko="그가 와 있다").exists()


def test_analysis_made_stale_while_judging_saves_nothing(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    fake_llm.before_rematch = lambda: SentenceAnalysis.objects.filter(
        translation_ko="그가 와 있다"
    ).update(is_stale=True, generation=F("generation") + 1)

    response = analyze(client, KITEIRU)

    assert "error" not in response.json()
    assert response.json()["grammar"] == []
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert (analysis.matcher_version, analysis.span_matches.count()) == (0, 0)


def test_rematch_saved_first_by_another_request_is_rolled_back(client, fake_llm):
    cache_then_register_teiru(client, fake_llm)

    def other_request_saves_first():
        # 재판정 잠금이 만료된 사이 다른 요청이 잠금을 다시 잡아 먼저 저장한다(#114).
        with jobs._connection() as redis_connection:
            redis_connection.delete(*redis_connection.keys("rematch:*"))
        fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
        analyze(connected_client(), KITEIRU)
        fake_llm.rematch_response = {
            "spans": [
                span_answer(
                    0,
                    "unfound",
                    new_usage=new_usage("결과 상태", "결과가 남아 있다", "窓が開いている"),
                )
            ]
        }

    fake_llm.before_rematch = other_request_saves_first

    response = analyze(client, KITEIRU)

    assert [item["name"] for item in response.json()["grammar"]] == ["진행"]
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert analysis.span_matches.count() == 1
    assert not GrammarUsage.objects.filter(name="결과 상태").exists()


@pytest.mark.parametrize("rejected", [False, True])
def test_fallback_shows_new_decided_spans_unless_rejected_meanwhile(client, fake_llm, rejected):
    # 캐시 문장에 용법 완결 ている(DB 확정)와 미검수 が(판별 대상)가 새로 걸린다.
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, KITEIRU)
    teiru = closed_teiru(fake_llm)
    register(fake_llm, "雨が降る", GA)
    fake_llm.forget_requests()
    fake_llm.rematch_error = BusinessError(AnalysisError.FAILED, "LLM 재판정 호출 실패")
    if rejected:
        fake_llm.before_rematch = lambda: review.reject_pattern(teiru)

    response = analyze(client, KITEIRU)

    assert [item["name"] for item in response.events[0]["grammar"]] == ["진행"]
    expected = [] if rejected else ["진행"]
    assert [item["name"] for item in response.json()["grammar"]] == expected
    assert not SpanMatch.objects.filter(analysis__translation_ko="그가 와 있다").exists()


@pytest.mark.parametrize("made_stale", [False, True])
def test_first_usage_added_by_rematch_raises_the_version_unless_rolled_back(
    client, fake_llm, made_stale
):
    cache_then_register_teiru(client, fake_llm)
    usage = GrammarUsage.objects.get(name="진행")

    def only_usage_rejected():
        # 판정을 기다리는 사이 하나뿐인 용법이 반려돼 ている가 매칭 자격을 잃는다.
        review.reject_usage(usage)
        if made_stale:
            SentenceAnalysis.objects.filter(translation_ko="그가 와 있다").update(
                is_stale=True, generation=F("generation") + 1
            )

    fake_llm.before_rematch = only_usage_rejected
    fake_llm.rematch_response = {
        "spans": [
            span_answer(
                0, "unfound", new_usage=new_usage("결과 상태", "결과가 남아 있다", "窓が開いている")
            )
        ]
    }
    before = version()

    analyze(client, KITEIRU)

    assert version() == before + (0 if made_stale else 1)
    assert GrammarUsage.objects.filter(name="결과 상태").exists() is not made_stale
