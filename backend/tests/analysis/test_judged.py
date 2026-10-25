"""분석 API: 첫 LLM 응답이 판정한 문법·고른 뜻을 저장 전에 보낸다(#97)."""

import pytest
from django.db import transaction

from analysis import jobs, patterns
from analysis.models import GrammarPattern
from tests.analysis.helpers import add_word, analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"


@pytest.fixture
def teiru(client, fake_llm):
    """진행(후보 1)과 결과 상태(후보 2) 두 용법을 가진 ている."""
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [new_pattern((1, "lemma"), (2, "lemma"))],
    }
    analyze(client, "走っている")
    pattern = GrammarPattern.objects.get()
    with transaction.atomic():
        patterns.add_usage(pattern, "결과 상태", "동작의 결과가 남아 있다", None)
    fake_llm.forget_requests()
    return pattern


def judged(response):
    [event] = (e for e in response.events if e["type"] == "judged")
    return event


def test_chosen_usage_is_sent_as_grammar_before_the_analysis(client, fake_llm, teiru):
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 2)]}

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "judged", "analysis"]
    event = judged(response)
    # 판정을 기다리던 구간이 고른 용법의 카드가 된다. LLM이 만든 용법이라 미검수다.
    assert [
        (g["start"], g["end"], g["name"], g["state"], g["review_status"]) for g in event["grammar"]
    ] == [(3, 6, "결과 상태", "decided", "pending")]
    assert event["checking"] == []
    assert event["words"] == []


@pytest.mark.parametrize(
    "answer, checking",
    [
        # 해석 갈림은 다시 묻고, 미발견은 새 용법을 저장해야 카드가 된다.
        (span_answer(0, "divergent", 1), 1),
        (
            span_answer(
                0,
                "unfound",
                new_usage={
                    "usage_name": "습관",
                    "explanation_ko": "되풀이되는 동작",
                    "example_ja": "毎朝走っている",
                },
            ),
            1,
        ),
        (span_answer(0, "unresolved"), 1),
        # 해당 없음은 확인 중에서 뺀다.
        (span_answer(0, "not_applicable"), 0),
    ],
)
def test_span_still_waiting_stays_checking(client, fake_llm, teiru, answer, checking):
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [answer]}

    event = judged(analyze(client, KITEIRU))

    assert event["grammar"] == []
    assert len(event["checking"]) == checking


def test_judged_message_carries_only_ids_and_positions(client, fake_llm, teiru, monkeypatch):
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 2)]}
    usage = teiru.usages.get(name="결과 상태")
    published = []
    original = jobs.publish

    def recording(sentence_hash, message):
        published.append(message)
        original(sentence_hash, message)

    monkeypatch.setattr(jobs, "publish", recording)

    analyze(client, KITEIRU)

    [message] = (m for m in published if m["type"] == "judged")
    assert {key: message[key] for key in ("spans", "word_spans")} == {
        "spans": [
            {
                "pattern_id": teiru.id,
                "start_token": 3,
                "end_token": 4,
                "state": "decided",
                "usage_id": usage.id,
            }
        ],
        # 판정 칸만 먼저 알려 단어는 아직 없다(#204).
        "word_spans": None,
    }


def test_sentence_without_spans_or_words_to_choose_sends_no_judged_event(client, fake_llm):
    fake_llm.response = {"translation_ko": "그가 와 있다"}

    response = analyze(client, KITEIRU)

    assert "judged" not in response.types()


def recording_publish(monkeypatch, fake_llm):
    """알린 소식마다 (종류, 그때 응답 전체를 넘겼는가)를 남긴다."""
    published = []
    original = jobs.publish

    def recording(sentence_hash, message):
        published.append((message["type"], fake_llm.result_given))
        original(sentence_hash, message)

    monkeypatch.setattr(jobs, "publish", recording)
    return published


def test_judgments_are_sent_as_soon_as_the_spans_section_closes(
    client, fake_llm, teiru, monkeypatch
):
    # 판정 칸이 닫히면 새 구문·단어 칸을 기다리지 않고 보낸다(#204).
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 2)]}
    published = recording_publish(monkeypatch, fake_llm)

    response = analyze(client, KITEIRU)

    assert ("judged", False) in published
    assert [g["name"] for g in judged(response)["grammar"]] == ["결과 상태"]
    assert [g["name"] for g in response.json()["grammar"]] == ["결과 상태"]


def test_wrong_spans_section_sends_no_judgments_and_fails(client, fake_llm, teiru, monkeypatch):
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 9)]}
    published = recording_publish(monkeypatch, fake_llm)

    response = analyze(client, KITEIRU)

    assert "judged" not in [kind for kind, _ in published]
    assert response.types()[-1] == "error"


def test_wrong_later_section_fails_after_the_judgments(client, fake_llm, teiru):
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "spans": [span_answer(0, "usage", 2)],
        "new_patterns": "not a list",
    }

    response = analyze(client, KITEIRU)

    assert response.types() == ["grammar", "translation", "judged", "error"]


def test_word_choices_sent_later_keep_the_judged_grammar(client, fake_llm, teiru):
    # 고른 뜻을 알리는 judged도 화면의 문법을 통째로 바꾸므로 앞서 알린 판정을 함께 싣는다(#205).
    hiraku = add_word(6, ["開く"], ["ひらく"], [(["to open"], [], None), (["to bloom"], [], None)])
    bloom = hiraku.senses.get(jmdict_sense_index=2).id
    # 토큰: 0 本 / 1 を / 2 開い / 3 て / 4 いる
    fake_llm.response = {
        "translation_ko": "책을 펼치고 있다",
        "spans": [span_answer(0, "usage", 2)],
        "words": [{"token_id": 2, "sense_id": bloom}],
    }

    response = analyze(client, "本を開いている")

    events = [e for e in response.events if e["type"] == "judged"]
    assert [[g["name"] for g in e["grammar"]] for e in events] == [["결과 상태"], ["결과 상태"]]
    assert [w["sense"] is not None for w in events[-1]["words"]] == [True]
