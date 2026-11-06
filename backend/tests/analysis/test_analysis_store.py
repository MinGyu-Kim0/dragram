"""선점한 분석 행을 이번 결과로 바꾸는 저장(#41, #98, #99)."""

import pytest
from django.db.models import F

from analysis.analysis_store import store
from analysis.models import GrammarPattern, SentenceAnalysis, SpanMatch
from analysis.reask import prepare
from analysis.sentence import Sentence
from analysis.span_rows import _PatternTaken
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import analyze, new_pattern, register

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEXT = "走っている"


def proposal():
    return {
        "tokens": [(1, "lemma"), (2, "lemma")],
        "pattern_name": "ている",
        "usage_name": "진행",
        "explanation_ko": "동작이 이어지고 있음을 나타낸다",
        "example_ja": "雨が降っている",
        "korean_equivalent": None,
        "function_tags": [],
        "connection_form": None,
        "connection_filled": True,
    }


def answers(sentence, *proposals, translation="새 번역"):
    validated = {
        "translation_ko": translation,
        "spans": [],
        "new_patterns": list(proposals),
        "words": {},
        "name_spans": [],
    }
    return prepare(sentence, validated)


def row():
    return SentenceAnalysis.objects.get(sentence_hash=Sentence(TEXT).sentence_hash)


@pytest.fixture
def sentence(client, fake_llm):
    """분석해 둔 행을 작업자가 다시 선점한 상태의 문장."""
    fake_llm.response = {"translation_ko": "옛 번역"}
    analyze(client, TEXT)
    SentenceAnalysis.objects.update(
        status=SentenceAnalysis.Status.PROCESSING, processing_translation_ko="쓰는 중"
    )
    return Sentence(TEXT)


def test_saving_completes_the_row_with_this_result(sentence):
    outdated = store(sentence, answers(sentence), False)

    saved = row()
    assert outdated is False
    assert (saved.status, saved.translation_ko) == ("complete", "새 번역")
    assert saved.processing_translation_ko is None
    assert saved.is_stale is False


def test_new_pattern_is_registered_with_its_span(sentence):
    store(sentence, answers(sentence, proposal()), False)

    pattern = GrammarPattern.objects.get(name="ている")
    span = row().span_matches.get()
    assert (span.pattern_id, span.start_offset, span.end_offset) == (pattern.id, 2, 5)


def test_saving_replaces_the_spans_of_the_earlier_result(sentence):
    store(sentence, answers(sentence, proposal()), False)
    SentenceAnalysis.objects.update(status=SentenceAnalysis.Status.PROCESSING)

    store(sentence, answers(sentence), False)

    assert not SpanMatch.objects.exists()


def test_older_attempt_is_rolled_back_when_the_generation_rose(sentence):
    SentenceAnalysis.objects.update(generation=F("generation") + 1)

    outdated = store(sentence, answers(sentence, proposal()), False)

    saved = row()
    assert outdated is True
    assert (saved.status, saved.translation_ko) == ("processing", "옛 번역")
    assert not SpanMatch.objects.exists()
    assert not GrammarPattern.objects.exists()


def test_pattern_taken_meanwhile_is_left_for_the_caller_to_ask_again(sentence, fake_llm):
    validated = answers(sentence, proposal())
    register(fake_llm, "歩いている", new_pattern((1, "lemma"), (2, "lemma")))

    with pytest.raises(_PatternTaken):
        store(sentence, validated, False)

    assert row().status == "processing"


def test_final_try_saves_without_the_pattern_someone_else_took(sentence, fake_llm):
    validated = answers(sentence, proposal())
    register(fake_llm, "歩いている", new_pattern((1, "lemma"), (2, "lemma")))

    assert store(sentence, validated, True) is False

    assert row().status == "complete"


def test_divergent_span_that_was_not_asked_again_is_not_saved(sentence):
    validated = {**answers(sentence), "spans": [(SpanMatch.State.DIVERGENT, None, None)]}

    with pytest.raises(BusinessError) as error:
        store(sentence, validated, False)

    assert error.value.error_code == AnalysisError.FAILED
    assert row().status == "processing"
