"""내 일본어: 내 문장들에 나온 용법(#313)과 단어 뜻(#314)을 모아 본다(FR-M10, ADR 0002).
웹 세션으로 본인 기록만 다루고 LLM을 부르지 않는다.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from analysis.models import (
    GrammarUsage,
    MatchCorrection,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
    UserSentence,
)
from tests.accounts.test_withdrawal import web_session
from tests.analysis.helpers import add_word, analyze, connected_client
from tests.analysis.test_my_sentences import GRAMMAR_RESPONSE, GRAMMAR_SENTENCE

pytestmark = pytest.mark.django_db

User = get_user_model()
GRAMMAR = "/api/my-japanese/grammar/"
WORDS = "/api/my-japanese/words/"
# 숫자만 달라 GRAMMAR_SENTENCE와 같은 분석을 쓰는 원문
SAME_ANALYSIS = "私は4人で走っている。"


def analyzed(username, fake_llm, *texts):
    client = connected_client(username)
    fake_llm.response = GRAMMAR_RESPONSE
    for text in texts:
        analyze(client, text)
    return User.objects.get(username=username)


def sentence_ids(user, *texts):
    return [UserSentence.objects.get(user=user, original_text=t).pk for t in texts]


def grammar(user):
    web, _ = web_session(user)
    response = web.get(GRAMMAR)
    assert response.status_code == 200
    return response.json()["usages"]


def span(pattern_name):
    return SpanMatch.objects.get(pattern__name=pattern_name)


def test_lists_each_usage_once_with_the_sentences_it_came_from(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE, SAME_ANALYSIS)
    analyzed("other", fake_llm, GRAMMAR_SENTENCE)
    fake_llm.forget_requests()

    usages = grammar(me)

    assert fake_llm.all_requests() == []
    ids = sentence_ids(me, SAME_ANALYSIS, GRAMMAR_SENTENCE)
    # 다른 사용자의 같은 문장은 세지 않는다. 문장은 최근 분석 순이다.
    assert usages == [
        {
            "usage_id": span("人で").usage_id,
            "pattern_name": "人で",
            "name": "인원",
            "explanation_ko": "함께하는 사람 수를 나타낸다",
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "review_status": "pending",
            "sentences": [
                {"id": ids[0], "text": SAME_ANALYSIS},
                {"id": ids[1], "text": GRAMMAR_SENTENCE},
            ],
        },
        {
            "usage_id": span("ている").usage_id,
            "pattern_name": "ている",
            "name": "진행",
            "explanation_ko": "동작이 이어지고 있음을 나타낸다",
            "korean_equivalent": None,
            "korean_equivalent_review_status": None,
            "review_status": "pending",
            "sentences": [
                {"id": ids[0], "text": SAME_ANALYSIS},
                {"id": ids[1], "text": GRAMMAR_SENTENCE},
            ],
        },
    ]


def test_more_often_met_usages_come_first(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE)
    ている = span("ている")
    # ている만 있는 다른 분석의 내 문장 하나를 더한다.
    other = SentenceAnalysis.objects.create(
        sentence_hash="0" * 64,
        normalize_version=1,
        normalized_length=7,
        status=SentenceAnalysis.Status.COMPLETE,
        word_spans=[],
    )
    SpanMatch.objects.create(
        analysis=other,
        pattern=ている.pattern,
        usage=ている.usage,
        start_offset=3,
        end_offset=5,
        state=SpanMatch.State.DECIDED,
        decided_by=SpanMatch.DecidedBy.LLM,
    )
    UserSentence.objects.create(
        user=me,
        original_hash="1" * 64,
        original_text="雨が降っている。",
        analysis=other,
        last_analyzed_at=timezone.now(),
    )

    usages = grammar(me)

    assert [(u["pattern_name"], len(u["sentences"])) for u in usages] == [
        ("ている", 2),
        ("人で", 1),
    ]


def test_rejected_usage_is_left_out_and_approved_has_no_pending_badge(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE)
    GrammarUsage.objects.filter(pk=span("人で").usage_id).update(status=ReviewStatus.REJECTED)
    ている = span("ている")
    GrammarUsage.objects.filter(pk=ている.usage_id).update(status=ReviewStatus.APPROVED)
    ている.pattern.status = ReviewStatus.APPROVED
    ている.pattern.save()

    usages = grammar(me)

    assert [(u["pattern_name"], u["review_status"]) for u in usages] == [("ている", "approved")]


def test_active_correction_counts_the_corrected_usage_and_release_drops_it(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE)
    ている, 人で = span("ている"), span("人で")
    corrected = GrammarUsage.objects.create(
        pattern=ている.pattern,
        name="결과 상태",
        explanation_ko="동작의 결과가 남아 있음을 나타낸다",
        status=ReviewStatus.PENDING,
        origin=GrammarUsage.Origin.ADMIN,
    )
    for target, after in ((ている, corrected), (人で, None)):
        MatchCorrection.objects.create(
            analysis=target.analysis,
            start_offset=target.start_offset,
            end_offset=target.end_offset,
            before_usage=target.usage,
            after_usage=after,
        )

    usages = grammar(me)

    assert [(u["usage_id"], u["name"]) for u in usages] == [(corrected.pk, "결과 상태")]


def test_unresolved_spans_are_not_listed(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE)
    SpanMatch.objects.filter(pk=span("人で").pk).update(
        state=SpanMatch.State.UNRESOLVED, usage=None
    )

    assert [u["pattern_name"] for u in grammar(me)] == ["ている"]


def test_needs_a_logged_in_web_session(fake_llm):
    analyzed("me", fake_llm, GRAMMAR_SENTENCE)

    for client in (Client(), connected_client("me2")):
        response = client.get(GRAMMAR)
        assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


@pytest.mark.parametrize(("show_parts", "listed"), [(True, ["人で", "ている"]), (False, ["人で"])])
def test_parts_hidden_by_the_outer_pattern_are_not_listed(fake_llm, show_parts, listed):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE)
    人で, ている = span("人で"), span("ている")
    # 人で의 용법으로 ている를 감싸는 바깥 구간을 둔다. 문장 화면처럼 show_parts를 따른다.
    SpanMatch.objects.create(
        analysis=ている.analysis,
        pattern=人で.pattern,
        usage=人で.usage,
        start_offset=ている.start_offset - 1,
        end_offset=ている.end_offset,
        state=SpanMatch.State.DECIDED,
        decided_by=SpanMatch.DecidedBy.LLM,
    )
    人で.pattern.show_parts = show_parts
    人で.pattern.save()

    assert [u["pattern_name"] for u in grammar(me)] == listed


def test_divergent_span_counts_only_its_main_usage(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE)
    人で, ている = span("人で"), span("ている")
    人で.delete()
    ている.state = SpanMatch.State.DIVERGENT
    ている.alternatives = [{"usage_id": 人で.usage_id, "translation_ko": "다른 번역"}]
    ている.save()

    assert [u["pattern_name"] for u in grammar(me)] == ["ている"]


def words(user):
    web, _ = web_session(user)
    response = web.get(WORDS)
    assert response.status_code == 200
    return response.json()["words"]


def with_senses(user, text, *senses):
    """그 내 문장의 분석에 고른 뜻들을 둔다."""
    analysis = UserSentence.objects.get(user=user, original_text=text).analysis
    analysis.sense_ids = [s.pk for s in senses]
    analysis.save()


def test_words_lists_each_sense_once_with_the_sentences_it_came_from(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE, SAME_ANALYSIS)
    analyzed("other", fake_llm, GRAMMAR_SENTENCE)
    run = add_word(1, ["走る"], ["はしる"], [(["to run"], ["v5r"], None)], tags=("verb", "group1"))
    sense = run.senses.get()
    sense.meaning_ko = "달리다"
    sense.save()
    with_senses(me, GRAMMAR_SENTENCE, sense)
    fake_llm.forget_requests()

    listed = words(me)

    assert fake_llm.all_requests() == []
    ids = sentence_ids(me, SAME_ANALYSIS, GRAMMAR_SENTENCE)
    assert listed == [
        {
            "sense_id": sense.pk,
            "dictionary_form": "走る",
            "reading": "はしる",
            "tags": ["group1", "verb"],
            "in_dictionary": True,
            "sense": {
                "tags": ["v5r"],
                "gloss_en": ["to run"],
                "origin": "jmdict",
                "status": "approved",
                "meaning_ko": "달리다",
                "meaning_status": "ai",
            },
            "sentences": [
                {"id": ids[0], "text": SAME_ANALYSIS},
                {"id": ids[1], "text": GRAMMAR_SENTENCE},
            ],
        }
    ]


def test_words_leaves_out_rejected_and_missing_senses_and_orders_by_count(fake_llm):
    me = analyzed("me", fake_llm, GRAMMAR_SENTENCE)
    other = SentenceAnalysis.objects.create(
        sentence_hash="0" * 64,
        normalize_version=1,
        normalized_length=7,
        status=SentenceAnalysis.Status.COMPLETE,
        word_spans=[],
    )
    UserSentence.objects.create(
        user=me,
        original_hash="1" * 64,
        original_text="雨が降っている。",
        analysis=other,
        last_analyzed_at=timezone.now(),
    )
    rain = add_word(1, ["雨"], ["あめ"], [(["rain"], [], None)]).senses.get()
    person = add_word(2, ["人"], ["ひと"], [(["person"], [], None)]).senses.get()
    rejected = add_word(3, ["私"], ["わたし"], [(["I"], [], None)]).senses.get()
    rejected.sense_status = ReviewStatus.REJECTED
    rejected.save()
    with_senses(me, GRAMMAR_SENTENCE, person, rejected, rain)
    other.sense_ids = [rain.pk, 999999]
    other.save()

    assert [w["dictionary_form"] for w in words(me)] == ["雨", "人"]


def test_words_needs_a_logged_in_web_session(fake_llm):
    for client in (Client(), connected_client("me2")):
        response = client.get(WORDS)
        assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})
