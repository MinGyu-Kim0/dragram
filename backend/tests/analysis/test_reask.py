"""새 구문 정리와, 해석 갈림·미확정 구간과 같은 조건 패턴을 한 번에 다시 묻기(#40)."""

import pytest

from analysis import llm
from analysis.models import GrammarPattern, ReviewStatus, SpanMatch
from analysis.reask import ask_again, prepare
from analysis.sentence import Sentence
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import new_pattern, register, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEXT = "走っている"
TEIRU_TOKENS = [(1, "lemma"), (2, "lemma")]


def still_current():
    return False


def proposal(tokens=None):
    return {"tokens": tokens or TEIRU_TOKENS, "pattern_name": "ている", "usage_name": "진행"}


def answers(*proposals):
    return {
        "translation_ko": "달리고 있다",
        "spans": [],
        "new_patterns": list(proposals),
        "words": {},
    }


def register_teiru(fake_llm):
    return register(fake_llm, TEXT, new_pattern((1, "lemma"), (2, "lemma")))


@pytest.fixture
def llm_client(fake_llm):
    return llm.get_client(lambda **_: None)


def test_proposal_that_follows_the_pattern_rules_gets_its_conditions():
    [made] = prepare(Sentence(TEXT), answers(proposal()))["new_patterns"]

    assert [c.lemma for c in made["conditions"]] == ["て", "居る"]
    assert made["existing"] is None


@pytest.mark.parametrize(
    "tokens",
    [
        [(1, "any"), (2, "lemma")],
        [(1, "lemma"), (2, "any")],
        [(0, "lemma")],
        [(0, "lemma"), (2, "lemma")],
    ],
    ids=["starts-with-any", "ends-with-any", "content-word-only", "gap"],
)
def test_proposal_breaking_the_pattern_rules_has_no_conditions(tokens):
    [made] = prepare(Sentence(TEXT), answers(proposal(tokens)))["new_patterns"]

    assert made["conditions"] is None


def test_proposal_over_an_already_matched_span_is_dropped(fake_llm):
    register_teiru(fake_llm)

    prepared = prepare(Sentence(TEXT), answers(proposal()))

    assert prepared["new_patterns"] == []
    assert len(prepared["span_list"]) == 1


def test_same_proposal_twice_stays_once():
    prepared = prepare(Sentence(TEXT), answers(proposal(), proposal()))

    assert len(prepared["new_patterns"]) == 1


def test_nothing_to_ask_again_makes_no_call(fake_llm, llm_client):
    sentence = Sentence(TEXT)
    prepared = prepare(sentence, answers(proposal()))

    asked = ask_again(sentence, llm_client, prepared, still_current)

    assert fake_llm.rejudge_requests == []
    assert len(asked["new_patterns"]) == 1


def test_proposal_whose_pattern_now_exists_is_asked_as_a_span(fake_llm, llm_client):
    sentence = Sentence(TEXT)
    prepared = prepare(sentence, answers(proposal()))
    register_teiru(fake_llm)
    fake_llm.rejudge_response = {"spans": [span_answer(0, "usage", 1)]}

    asked = ask_again(sentence, llm_client, prepared, still_current)

    [request] = fake_llm.rejudge_requests
    assert request["recheck_spans"] == []
    assert [span["start_token_id"] for span in request["spans"]] == [1]
    assert asked["new_patterns"] == []
    assert [state for state, _, _ in asked["spans"]] == [SpanMatch.State.DECIDED]
    assert len(asked["span_list"]) == 1
    assert asked["rechecked"] is True


def test_job_whose_result_will_be_dropped_does_not_ask(fake_llm, llm_client):
    sentence = Sentence(TEXT)
    prepared = prepare(sentence, answers(proposal()))
    register_teiru(fake_llm)

    asked = ask_again(sentence, llm_client, prepared, lambda: True)

    assert asked is prepared
    assert fake_llm.rejudge_requests == []


def test_rejected_pattern_is_not_asked_and_stays_unfound(fake_llm, llm_client):
    sentence = Sentence(TEXT)
    prepared = prepare(sentence, answers(proposal()))
    pattern = register_teiru(fake_llm)
    GrammarPattern.objects.filter(pk=pattern.pk).update(status=ReviewStatus.REJECTED)

    asked = ask_again(sentence, llm_client, prepared, still_current)

    assert fake_llm.rejudge_requests == []
    assert asked["new_patterns"][0]["existing"] == GrammarPattern.objects.get(pk=pattern.pk)


@pytest.mark.parametrize(
    "response",
    ["거절", {"spans": [span_answer(9, "usage", 1)]}],
    ids=["not-an-object", "unknown-span"],
)
def test_wrong_answer_fails_the_analysis(fake_llm, llm_client, response):
    sentence = Sentence(TEXT)
    prepared = prepare(sentence, answers(proposal()))
    register_teiru(fake_llm)
    fake_llm.rejudge_response = response

    with pytest.raises(BusinessError) as error:
        ask_again(sentence, llm_client, prepared, still_current)

    assert error.value.error_code == AnalysisError.FAILED
