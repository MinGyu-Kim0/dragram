"""해석 갈림·미확정 구간(#40)."""

import threading

import pytest
from django.db import connection, transaction

from analysis import patterns, review
from analysis.models import GrammarPattern, SentenceAnalysis, SpanMatch
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, connected_client, new_pattern, new_usage, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"
BASIS = "앞에서 이미 도착했다고 말했다면"


def teiru_with_two_usages(client, fake_llm):
    """진행(후보 1)과 결과 상태(후보 2) 두 용법을 가진 ている."""
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [new_pattern((1, "lemma"), (2, "lemma"))],
    }
    analyze(client, "走っている")
    pattern = GrammarPattern.objects.get()
    with transaction.atomic():
        result, _ = patterns.add_usage(pattern, "결과 상태", "동작의 결과가 남아 있다", None)
    return pattern, pattern.usages.get(name="진행"), result


def divergent(span_id, candidate_id, *alternatives):
    return {**span_answer(span_id, "divergent", candidate_id), "alternatives": list(alternatives)}


def alternative(candidate_id, translation_ko, basis=BASIS):
    return {"candidate_id": candidate_id, "translation_ko": translation_ko, "basis": basis}


def test_divergent_span_is_asked_again_once_and_saved_with_its_alternatives(client, fake_llm):
    _, progress, result = teiru_with_two_usages(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))],
    }

    response = analyze(client, KITEIRU)

    [rejudge] = fake_llm.rejudge_requests
    assert rejudge["recheck_spans"] == [
        {
            "span_id": 0,
            "start_token_id": 3,
            "end_token_id": 4,
            "candidates": [
                {
                    "candidate_id": 1,
                    "name": "진행",
                    "explanation_ko": "동작이 이어지고 있음을 나타낸다",
                },
                {
                    "candidate_id": 2,
                    "name": "결과 상태",
                    "explanation_ko": "동작의 결과가 남아 있다",
                },
            ],
        }
    ]
    assert rejudge["spans"] == []
    span = SpanMatch.objects.get(
        analysis__in=SentenceAnalysis.objects.filter(translation_ko="그가 와 있다")
    )
    assert span.state == "divergent"
    assert span.usage == progress
    assert span.alternatives == [{"usage_id": result.id, "translation_ko": "그가 와 있는 상태다"}]
    assert response.json()["grammar"] == [
        {
            "start": 3,
            "end": 6,
            "state": "divergent",
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
            "alternatives": [
                {
                    "name": "결과 상태",
                    "translation_ko": "그가 와 있는 상태다",
                    "review_status": "pending",
                }
            ],
        }
    ]


def ask_divergent(client, fake_llm, rejudge_spans, translation="그가 와 있다", first=None):
    """ている(진행·결과 상태)의 첫 응답이 해석 갈림인 문장을 분석한다."""
    pattern, progress, result = teiru_with_two_usages(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [first or span_answer(0, "divergent", 1)],
    }
    fake_llm.rejudge_response = {"translation_ko": translation, "spans": rejudge_spans}
    return analyze(client, KITEIRU), pattern, progress, result


def saved_span():
    return SpanMatch.objects.get(analysis=SentenceAnalysis.objects.latest("id"))


def test_translation_is_replaced_when_the_main_reading_changes(client, fake_llm):
    response, *_ = ask_divergent(
        client,
        fake_llm,
        [divergent(0, 2, alternative(1, "그가 오고 있다"))],
        translation="그가 와 있는 상태다",
    )

    assert response.json()["translation_ko"] == "그가 와 있는 상태다"
    assert SentenceAnalysis.objects.latest("id").translation_ko == "그가 와 있는 상태다"


@pytest.mark.parametrize(
    "answer",
    [
        divergent(0, 1, alternative(2, "그가 와 있는 상태다")),
        span_answer(0, "unresolved"),
    ],
)
def test_translation_is_kept_when_the_main_reading_stays_or_is_unresolved(client, fake_llm, answer):
    response, *_ = ask_divergent(client, fake_llm, [answer], translation="바뀐 번역")

    assert response.json()["translation_ko"] == "그가 와 있다"


def test_translation_is_replaced_when_an_unresolved_span_is_decided(client, fake_llm):
    response, *_ = ask_divergent(
        client,
        fake_llm,
        [span_answer(0, "usage", 2)],
        translation="그가 와 있는 상태다",
        first=span_answer(0, "unresolved"),
    )

    assert response.json()["translation_ko"] == "그가 와 있는 상태다"
    assert saved_span().state == "decided"


@pytest.mark.parametrize("basis", ["", "   ", "…!?", "​\n", None])
def test_divergent_span_whose_alternatives_have_no_basis_is_saved_as_unresolved(
    client, fake_llm, basis
):
    response, *_ = ask_divergent(
        client, fake_llm, [divergent(0, 1, alternative(2, "그가 와 있는 상태다", basis))]
    )

    span = saved_span()
    assert (span.state, span.usage, span.alternatives) == ("unresolved", None, None)
    assert span.analysis.status == SentenceAnalysis.Status.COMPLETE
    assert response.json()["grammar"] == [
        {
            "start": 3,
            "end": 6,
            "state": "unresolved",
            "name": "ている",
            "explanation_ko": None,
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
        }
    ]


def test_only_the_span_without_basis_becomes_unresolved(client, fake_llm):
    teiru_with_two_usages(client, fake_llm)
    # 토큰: 0 走っ / 1 て / 2 いる / 3 人 / 4 が / 5 来 / 6 て / 7 いる
    fake_llm.response = {
        "translation_ko": "달리고 있는 사람이 와 있다",
        "spans": [span_answer(0, "divergent", 1), span_answer(1, "divergent", 3)],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "달리고 있는 사람이 와 있다",
        "spans": [
            divergent(0, 1, alternative(2, "달려 있는 사람이 와 있다", "")),
            divergent(1, 3, alternative(4, "달리고 있는 사람이 와 있는 상태다")),
        ],
    }

    response = analyze(client, "走っている人が来ている")

    assert [item["state"] for item in response.json()["grammar"]] == ["unresolved", "divergent"]


def test_unresolved_span_asked_again_and_still_unresolved_is_saved_and_reused(client, fake_llm):
    response, *_ = ask_divergent(
        client, fake_llm, [span_answer(0, "unresolved")], first=span_answer(0, "unresolved")
    )
    calls = len(fake_llm.requests), len(fake_llm.rejudge_requests)

    again = analyze(client, KITEIRU)

    assert saved_span().state == "unresolved"
    assert [(item["state"], item["name"]) for item in response.json()["grammar"]] == [
        ("unresolved", "ている")
    ]
    # 미확정도 정상 판정이라 캐시를 LLM 없이 그대로 쓴다.
    assert (len(fake_llm.requests), len(fake_llm.rejudge_requests)) == calls
    assert again.json()["grammar"] == response.json()["grammar"]


def test_divergent_analysis_is_reused_from_the_cache_without_the_llm(client, fake_llm):
    response, *_ = ask_divergent(
        client, fake_llm, [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))]
    )
    calls = len(fake_llm.requests), len(fake_llm.rejudge_requests)

    again = analyze(client, KITEIRU)

    assert (len(fake_llm.requests), len(fake_llm.rejudge_requests)) == calls
    assert again.json()["grammar"] == response.json()["grammar"]


@pytest.mark.parametrize(
    "rejudge",
    [
        # 후보 밖 대안, 대안 = 주 용법, 같은 대안 두 번
        [divergent(0, 1, alternative(9, "다른 번역"))],
        [divergent(0, 1, alternative(1, "다른 번역"))],
        [divergent(0, 1, alternative(2, "다른 번역"), alternative(2, "또 다른 번역"))],
        # 다시 묻는 해석 갈림 구간은 미발견을 받지 않는다.
        [span_answer(0, "unfound")],
        # 대안 번역이 최종 번역과 같다.
        [divergent(0, 1, alternative(2, " 그가 와 있다 "))],
        # 대안 칸이 목록이 아니다.
        [{**span_answer(0, "divergent", 1), "alternatives": "결과 상태"}],
    ],
)
def test_invalid_answer_when_rechecking_fails_and_nothing_is_stored(client, fake_llm, rejudge):
    response, *_ = ask_divergent(client, fake_llm, rejudge)

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 1


def test_divergent_first_answer_on_a_span_with_one_candidate_fails(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [new_pattern((1, "lemma"), (2, "lemma"))],
    }
    analyze(client, "走っている")
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
    }

    response = analyze(client, KITEIRU)

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert fake_llm.rejudge_requests == []
    assert SentenceAnalysis.objects.count() == 1


@pytest.mark.parametrize("translation", ["", None, "⟨N1⟩ 그가 와 있다"])
def test_changed_translation_that_is_invalid_fails(client, fake_llm, translation):
    response, *_ = ask_divergent(
        client, fake_llm, [span_answer(0, "usage", 2)], translation=translation
    )

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert SentenceAnalysis.objects.count() == 1


def test_failed_recheck_call_fails_and_keeps_the_sent_translation(client, fake_llm):
    teiru_with_two_usages(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
    }
    fake_llm.rejudge_error = BusinessError(AnalysisError.FAILED, "LLM 다시 묻기 호출 실패")

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "error"]
    assert response.events[1]["translation_ko"] == "그가 와 있다"
    assert SentenceAnalysis.objects.count() == 1


def register_inactive_ga(client, fake_llm):
    """예문이 원문을 베껴 비활성인 が(주격) 패턴. 토큰: 0 犬 / 1 が / 2 走る"""
    fake_llm.response = {
        "translation_ko": "개가 달린다",
        "new_patterns": [
            new_pattern((1, "lemma"), pattern_name="が", usage_name="주격", example_ja="犬が走る")
        ],
    }
    analyze(client, "犬が走る")
    return GrammarPattern.objects.get(name="が")


def test_divergent_and_same_condition_spans_are_asked_in_one_call(client, fake_llm):
    teiru_with_two_usages(client, fake_llm)
    register_inactive_ga(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
        "new_patterns": [new_pattern((1, "lemma"), pattern_name="が", usage_name="다른 이름")],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [
            divergent(0, 1, alternative(2, "그가 와 있는 상태다")),
            span_answer(
                1,
                "unfound",
                new_usage=new_usage(
                    usage_name="주어",
                    explanation_ko="동작의 주체를 나타낸다",
                    example_ja="鳥が飛ぶ",
                ),
            ),
        ],
    }

    response = analyze(client, KITEIRU)

    [rejudge] = fake_llm.rejudge_requests
    assert [span["span_id"] for span in rejudge["recheck_spans"]] == [0]
    # 같은 조건 구간의 후보 ID는 다시 묻는 구간의 후보 다음부터 매긴다.
    assert rejudge["spans"] == [
        {
            "span_id": 1,
            "start_token_id": 1,
            "end_token_id": 1,
            "candidates": [
                {
                    "candidate_id": 3,
                    "name": "주격",
                    "explanation_ko": "동작이 이어지고 있음을 나타낸다",
                }
            ],
        }
    ]
    assert [(item["state"], item["name"]) for item in response.json()["grammar"]] == [
        ("decided", "주어"),
        ("divergent", "진행"),
    ]


def test_recheck_request_carries_decided_spans_but_not_the_first_answer(client, fake_llm):
    teiru_with_two_usages(client, fake_llm)
    # 토큰: 0 走っ / 1 て / 2 いる / 3 人 / 4 が / 5 来 / 6 て / 7 いる
    fake_llm.response = {
        "translation_ko": "달리고 있는 사람이 와 있다",
        "spans": [span_answer(0, "usage", 1), span_answer(1, "divergent", 3)],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "달리고 있는 사람이 와 있다",
        "spans": [divergent(0, 3, alternative(4, "달리고 있는 사람이 와 있는 상태다"))],
    }

    analyze(client, "走っている人が来ている")

    [rejudge] = fake_llm.rejudge_requests
    assert rejudge["translation_ko"] == "달리고 있는 사람이 와 있다"
    assert rejudge["decided_spans"] == [{"start_token_id": 1, "end_token_id": 2, "name": "진행"}]
    [recheck] = rejudge["recheck_spans"]
    assert set(recheck) == {"span_id", "start_token_id", "end_token_id", "candidates"}
    assert (recheck["start_token_id"], recheck["end_token_id"]) == (6, 7)


def test_same_condition_span_alone_is_asked_without_rechecking(client, fake_llm):
    teiru_with_two_usages(client, fake_llm)
    register_inactive_ga(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "usage", 1)],
        "new_patterns": [new_pattern((1, "lemma"), pattern_name="が", usage_name="다른 이름")],
    }
    fake_llm.rejudge_response = {"spans": [span_answer(0, "divergent", 1)]}

    response = analyze(client, KITEIRU)

    # 같은 조건 구간도 해석 갈림을 받지만, 후보가 하나라 근거 있는 대안이 없어 미확정이다.
    [rejudge] = fake_llm.rejudge_requests
    assert rejudge["recheck_spans"] == []
    assert [item["state"] for item in response.json()["grammar"]] == ["unresolved", "decided"]


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_second_call_after_pattern_taken_does_not_recheck_again(fake_llm, monkeypatch):
    teiru_with_two_usages(connected_client(), fake_llm)
    register = patterns.register

    def other_request_registers_first(*args):
        monkeypatch.setattr(patterns, "register", register)
        saved_response = fake_llm.response

        def other_request():
            try:
                register_inactive_ga(connected_client(), fake_llm)
            finally:
                connection.close()

        thread = threading.Thread(target=other_request)
        thread.start()
        thread.join()
        fake_llm.response = saved_response
        return register(*args)

    monkeypatch.setattr(patterns, "register", other_request_registers_first)
    judge = fake_llm.judge_spans

    def then_answer_the_same_condition_span(*args):
        answer = judge(*args)
        fake_llm.rejudge_response = {"spans": [span_answer(0, "usage", 1)]}
        return answer

    monkeypatch.setattr(fake_llm, "judge_spans", then_answer_the_same_condition_span)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
        "new_patterns": [new_pattern((1, "lemma"), pattern_name="が", usage_name="주격")],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))],
    }

    response = analyze(connected_client(), KITEIRU)

    first, second = fake_llm.rejudge_requests
    assert len(first["recheck_spans"]) == 1
    assert second["recheck_spans"] == []
    assert [span["start_token_id"] for span in second["spans"]] == [1]
    assert [item["state"] for item in response.json()["grammar"]] == ["decided", "divergent"]


def cached(client):
    SentenceAnalysis.objects.update(is_stale=False)
    return analyze(client, KITEIRU).json()["grammar"]


def test_rejected_alternative_is_left_out_and_rejected_main_usage_drops_the_span(client, fake_llm):
    _, progress, result = ask_divergent(
        client, fake_llm, [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))]
    )[1:]

    review.reject_usage(result)
    [item] = cached(client)
    assert (item["state"], item["alternatives"]) == ("divergent", [])

    review.reject_usage(progress)
    assert cached(client) == []


def test_alternative_of_approved_usage_and_patterns_is_approved(client, fake_llm):
    pattern, _, result = ask_divergent(
        client, fake_llm, [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))]
    )[1:]
    pattern.test_cases = [
        {"text": "雨が降っている", "should_match": True},
        {"text": "雨が降る", "should_match": False},
    ]
    pattern.save(update_fields=["test_cases"])
    review.approve_pattern(pattern)
    review.approve_usage(result)

    [item] = cached(client)
    assert item["review_status"] == "pending"
    assert item["alternatives"][0]["review_status"] == "approved"


def test_unresolved_span_of_a_rejected_pattern_is_left_out(client, fake_llm):
    pattern = ask_divergent(
        client, fake_llm, [span_answer(0, "unresolved")], first=span_answer(0, "unresolved")
    )[1]

    review.reject_pattern(pattern)

    assert cached(client) == []


@pytest.mark.parametrize("event", ["reject", "unapprove"])
def test_rejecting_or_unapproving_an_alternative_usage_makes_the_analysis_stale(
    client, fake_llm, event
):
    result = ask_divergent(
        client, fake_llm, [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))]
    )[3]
    analysis = SentenceAnalysis.objects.latest("id")
    generation = analysis.generation
    if event == "unapprove":
        review.approve_usage(result)
        SentenceAnalysis.objects.update(is_stale=False)
        review.unapprove_usage(result)
    else:
        review.reject_usage(result)

    analysis.refresh_from_db()
    assert analysis.is_stale
    assert analysis.generation > generation


def test_basis_is_kept_nowhere(client, fake_llm, caplog):
    secret = "앞 문장에서 이미 도착했다고 했다면"
    ask_divergent(
        client,
        fake_llm,
        [
            divergent(
                0,
                1,
                alternative(2, "그가 와 있는 상태다", secret),
            )
        ],
    )
    response = analyze(client, KITEIRU)
    # 실패해 로그가 남는 경우도 본다(후보 밖 대안).
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [divergent(0, 1, alternative(9, "다른 번역", secret))],
    }
    analyze(client, "彼が来ている。")

    rows = [str(row) for model in (SpanMatch, SentenceAnalysis) for row in model.objects.values()]
    assert not any(secret in row for row in rows)
    assert secret not in response.response.content.decode()
    assert secret not in caplog.text


def test_recheck_request_carries_spans_decided_without_the_llm(client, fake_llm):
    teiru_with_two_usages(client, fake_llm)
    # 토큰: 0 鳥 / 1 が / 2 飛ぶ. 예문이 통과해 활성인 が를 승인하고 용법 완결로 표시한다.
    fake_llm.response = {
        "translation_ko": "새가 난다",
        "new_patterns": [
            new_pattern((1, "lemma"), pattern_name="が", usage_name="주격", example_ja="犬が走る")
        ],
    }
    analyze(client, "鳥が飛ぶ")
    ga = GrammarPattern.objects.get(name="が")
    ga.test_cases = [
        {"text": "犬が走る", "should_match": True},
        {"text": "犬も走る", "should_match": False},
    ]
    ga.save(update_fields=["test_cases"])
    review.approve_pattern(ga)
    review.approve_usage(ga.usages.get())
    review.close_usages(ga)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))],
    }

    analyze(client, KITEIRU)

    [rejudge] = fake_llm.rejudge_requests
    assert rejudge["decided_spans"] == [{"start_token_id": 1, "end_token_id": 1, "name": "주격"}]


def test_divergent_span_not_asked_again_is_never_saved(client, fake_llm, monkeypatch):
    # 첫 호출을 기다리는 사이 다른 요청이 같은 문장을 저장해 재질문을 건너뛰었는데, 저장 직전에
    # 그 행이 stale이 되어 이 요청이 행을 다시 채우게 되는 경합
    teiru_with_two_usages(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "divergent", 1)],
    }
    fake_llm.rejudge_response = {
        "translation_ko": "그가 와 있다",
        "spans": [divergent(0, 1, alternative(2, "그가 와 있는 상태다"))],
    }
    fake_llm.before_respond = lambda: analyze(connected_client(), KITEIRU)
    get_or_create = SentenceAnalysis.objects.get_or_create

    def made_stale_before_saving(**kwargs):
        SentenceAnalysis.objects.filter(sentence_hash=kwargs["sentence_hash"]).update(is_stale=True)
        return get_or_create(**kwargs)

    monkeypatch.setattr(SentenceAnalysis.objects, "get_or_create", made_stale_before_saving)

    response = analyze(client, KITEIRU)

    assert response.types()[-1] == "error"
    # 다른 요청의 재질문만 있었다. 그 요청의 결과는 stale로 남아 다음 요청이 다시 분석한다.
    assert len(fake_llm.rejudge_requests) == 1
    assert SpanMatch.objects.filter(state="divergent").count() == 1
