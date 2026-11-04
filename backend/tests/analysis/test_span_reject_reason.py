"""후보 구간 판정 검증이 응답을 거부한 사유를 로그에 남긴다(#394)."""

import pytest

from tests.analysis.helpers import analyze, new_usage, span_answer
from tests.analysis.test_divergent import KITEIRU, alternative, ask_divergent, divergent
from tests.analysis.test_rematch import cache_then_register_teiru
from tests.analysis.test_single_usage import register_teiru

pytestmark = pytest.mark.django_db


def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


# ている(후보 1개) 구간 하나인 문장에 첫 응답이 낸 판정과 남길 사유
@pytest.mark.parametrize(
    ("spans", "reason"),
    [
        ("ている", "not_list"),
        (["ている"], "not_object answer=1"),
        ([], "missing_spans answered=0/1"),
        ([span_answer(3, "usage", 1)], "span_id_out_of_range answer=1 spans=1"),
        ([span_answer(0, "usage", 1)] * 2, "duplicate_span span=1/1"),
        ([span_answer(0, "maybe", 1)], "verdict_not_allowed span=1/1 verdict=?"),
        (
            [span_answer(0, "usage", 9)],
            "candidate_not_in_span span=1/1 verdict=usage candidates=1",
        ),
        ([span_answer(0, "divergent", 1)], "divergent_single_candidate span=1/1 candidates=1"),
        ([span_answer(0, "unfound")], "new_usage_invalid span=1/1"),
    ],
)
def test_first_answer_rejection_logs_the_rule(client, fake_llm, caplog, spans, reason):
    register_teiru(client, fake_llm)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": spans}

    response = analyze(client, KITEIRU)

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert f"ANALYSIS:FAILED: LLM 응답 검증 실패: 후보 구간 ({reason})" in warnings(caplog)


def test_rejection_log_has_no_sentence_or_llm_text(client, fake_llm, caplog):
    register_teiru(client, fake_llm)
    secret = "⟨N1⟩비밀 용법"
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "unfound", new_usage=new_usage(usage_name=secret))],
    }

    analyze(client, KITEIRU)

    assert "new_usage_invalid" in caplog.text
    for text in (KITEIRU, "그가 와 있다", "비밀"):
        assert text not in caplog.text


@pytest.mark.parametrize(
    ("rejudge", "reason"),
    [
        (
            [divergent(0, 1, alternative(9, "다른 번역"))],
            "alternatives_invalid span=1/1 verdict=divergent candidates=2",
        ),
        ([span_answer(0, "unfound")], "verdict_not_allowed span=1/1 verdict=unfound"),
    ],
)
def test_recheck_rejection_logs_the_rule(client, fake_llm, caplog, rejudge, reason):
    response, *_ = ask_divergent(client, fake_llm, rejudge)

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert f"ANALYSIS:FAILED: LLM 응답 검증 실패: 다시 묻기 ({reason})" in warnings(caplog)


def test_rematch_rejection_logs_the_rule(client, fake_llm, caplog):
    cache_then_register_teiru(client, fake_llm)
    fake_llm.rematch_response = {"spans": []}

    analyze(client, KITEIRU)

    assert any(
        message.startswith("rematch_judge 실패:")
        and message.endswith("LLM 응답 검증 실패: 재판정 (missing_spans answered=0/1)")
        for message in warnings(caplog)
    )
