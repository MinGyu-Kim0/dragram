"""분석 API: 고른 JMdict 뜻의 한국어 뜻을 한 번 만들어 모든 문장이 다시 쓴다(#97)."""

import pytest

from analysis import jobs
from analysis.models import SentenceAnalysis, UsageLog, WordSense
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import add_word, analyze

pytestmark = pytest.mark.django_db


@pytest.fixture
def gakusei():
    """학생: 뜻이 하나라 LLM 없이 정해진다."""
    return add_word(3, ["学生"], ["がくせい"], [(["student"], [], None)])


def only_sense(word):
    return word.senses.get()


def test_missing_meaning_is_made_once_and_reused_by_other_sentences(client, fake_llm, gakusei):
    fake_llm.gloss_response = {
        "senses": [{"sense_id": only_sense(gakusei).id, "meaning_ko": "학생"}]
    }

    first = analyze(client, "私は学生です。")
    second = analyze(client, "学生が来た。")

    assert len(fake_llm.gloss_requests) == 1
    for response in (first, second):
        [word] = response.json()["words"]
        assert (word["sense"]["meaning_ko"], word["sense"]["meaning_status"]) == ("학생", "ai")
    stored = only_sense(gakusei)
    assert (stored.meaning_ko, stored.meaning_source, stored.meaning_status) == (
        "학생",
        "llm",
        "ai",
    )
    assert UsageLog.objects.filter(purpose="word_gloss", success=True).count() == 1


@pytest.fixture
def hiraku():
    """開く(ひらく): 뜻이 둘이라 LLM이 고른다."""
    return add_word(
        6,
        ["開く"],
        ["ひらく"],
        [(["to open"], ["transitive"], None), (["to bloom"], ["intransitive"], None)],
        tags=("verb", "group1"),
    )


def test_only_chosen_senses_are_sent_with_dictionary_fields_and_no_sentence(
    client, fake_llm, hiraku
):
    # 토큰: 0 本 / 1 を / 2 開い / 3 た
    bloom = hiraku.senses.get(jmdict_sense_index=2)
    fake_llm.response = {
        "translation_ko": "책을 펼쳤다",
        "words": [{"token_id": 2, "sense_id": bloom.id}],
    }

    analyze(client, "本を開いた")

    assert fake_llm.gloss_requests == [
        [
            {
                "sense_id": bloom.id,
                "dictionary_form": "開く",
                "reading": "ひらく",
                "pos": "n",
                "gloss_en": ["to bloom"],
                "tags": ["intransitive"],
            }
        ]
    ]
    assert "本" not in str(fake_llm.gloss_requests)


def test_no_call_when_every_chosen_sense_has_a_meaning(client, fake_llm, gakusei):
    WordSense.objects.update(meaning_ko="학생", meaning_source="admin", meaning_status="reviewed")

    response = analyze(client, "私は学生です。")

    assert fake_llm.gloss_requests == []
    [word] = response.json()["words"]
    assert (word["sense"]["meaning_ko"], word["sense"]["meaning_status"]) == ("학생", "reviewed")


def test_failed_call_keeps_the_analysis_and_marks_the_senses_failed(client, fake_llm, gakusei):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}
    fake_llm.gloss_error = BusinessError(AnalysisError.FAILED, "가짜 실패")

    response = analyze(client, "私は学生です。")

    [word] = response.json()["words"]
    assert (word["sense"]["meaning_ko"], word["sense"]["meaning_status"]) == (None, "failed")
    row = SentenceAnalysis.objects.get()
    assert row.translation_ko == "나는 학생입니다."
    assert row.sense_ids == [only_sense(gakusei).id]
    assert UsageLog.objects.filter(purpose="word_gloss", success=False).count() == 1


@pytest.mark.parametrize(
    "answer",
    [
        lambda student, bloom: [],  # 답이 빠짐
        lambda student, bloom: [{"sense_id": bloom + 100, "meaning_ko": "학생"}],  # 요청 밖 ID
        lambda student, bloom: [{"sense_id": student, "meaning_ko": "  "}],
        lambda student, bloom: [{"sense_id": str(student), "meaning_ko": "학생"}],
        lambda student, bloom: [
            {"sense_id": student, "meaning_ko": "학생"},
            {"sense_id": student, "meaning_ko": "학도"},
        ],
        lambda student, bloom: ["not an object"],
    ],
)
def test_wrong_answer_fails_only_that_sense(client, fake_llm, gakusei, hiraku, answer):
    # 토큰: 0 学生 / 1 が / 2 開い / 3 た
    student = only_sense(gakusei).id
    bloom = hiraku.senses.get(jmdict_sense_index=2).id
    fake_llm.response = {
        "translation_ko": "학생이 피었다",
        "words": [{"token_id": 2, "sense_id": bloom}],
    }
    fake_llm.gloss_response = {
        "senses": [*answer(student, bloom), {"sense_id": bloom, "meaning_ko": "피다"}]
    }

    response = analyze(client, "学生が開いた")

    meanings = [
        (w["sense"]["meaning_ko"], w["sense"]["meaning_status"]) for w in response.json()["words"]
    ]
    assert meanings == [(None, "failed"), ("피다", "ai")]


def test_failed_sense_is_not_retried_from_cache_but_is_in_a_new_sentence(client, fake_llm, gakusei):
    fake_llm.gloss_response = {"senses": []}
    analyze(client, "私は学生です。")
    fake_llm.gloss_response = None

    cached = analyze(client, "私は学生です。")

    assert len(fake_llm.gloss_requests) == 1
    [word] = cached.json()["words"]
    assert word["sense"]["meaning_status"] == "failed"

    fresh = analyze(client, "学生が来た。")

    assert len(fake_llm.gloss_requests) == 2
    [word] = fresh.json()["words"]
    assert (word["sense"]["meaning_ko"], word["sense"]["meaning_status"]) == ("学生 뜻", "ai")


def test_meaning_saved_by_another_job_meanwhile_is_not_overwritten(client, fake_llm, gakusei):
    fake_llm.before_gloss = lambda: WordSense.objects.update(
        meaning_ko="먼저 저장", meaning_source="llm", meaning_status="ai"
    )

    response = analyze(client, "私は学生です。")

    assert only_sense(gakusei).meaning_ko == "먼저 저장"
    [word] = response.json()["words"]
    assert word["sense"]["meaning_ko"] == "먼저 저장"


def test_chosen_senses_and_new_meanings_are_sent_before_the_analysis(client, fake_llm, hiraku):
    # 토큰: 0 本 / 1 を / 2 開い / 3 た
    bloom = hiraku.senses.get(jmdict_sense_index=2).id
    fake_llm.response = {
        "translation_ko": "책을 펼쳤다",
        "words": [{"token_id": 2, "sense_id": bloom}],
    }
    fake_llm.gloss_response = {"senses": [{"sense_id": bloom, "meaning_ko": "피다"}]}

    response = analyze(client, "本を開いた")

    assert response.types() == ["grammar", "translation", "judged", "analysis"]
    # 고른 뜻이 analysis 전에 오고, 새 한국어 뜻은 그 뒤 analysis에 실린다. 테스트는 작업을 요청
    # 안에서 바로 실행해 words 이벤트를 만들 때도 한국어 뜻이 이미 저장돼 있다(작업자 쪽 순서는
    # 아래 테스트에서 본다).
    [chosen] = (e["words"] for e in response.events if e["type"] == "judged")
    assert [(w["start"], w["sense"]["tags"]) for w in chosen] == [(2, ["intransitive"])]
    [word] = response.events[-1]["words"]
    assert word["sense"]["meaning_ko"] == "피다"


def test_no_meaning_event_when_nothing_was_made(client, fake_llm, gakusei):
    WordSense.objects.update(meaning_ko="학생", meaning_source="admin", meaning_status="reviewed")

    response = analyze(client, "私は学生です。")

    # 뜻이 하나뿐이라 고를 것도, 만들 한국어 뜻도 없다.
    assert response.types() == ["grammar", "translation", "analysis"]


def test_worker_publishes_chosen_senses_before_making_meanings(
    client, fake_llm, hiraku, monkeypatch
):
    # 토큰: 0 本 / 1 を / 2 開い / 3 た
    bloom = hiraku.senses.get(jmdict_sense_index=2)
    fake_llm.response = {
        "translation_ko": "책을 펼쳤다",
        "words": [{"token_id": 2, "sense_id": bloom.id}],
    }
    published = []
    original = jobs.publish

    def recording(sentence_hash, message):
        bloom.refresh_from_db()
        published.append((message["type"], message.get("word_spans"), bloom.meaning_ko))
        original(sentence_hash, message)

    monkeypatch.setattr(jobs, "publish", recording)

    analyze(client, "本を開いた")

    # 소식에는 키 텍스트 위치와 뜻 ID만 싣는다.
    spans = [{"start": 2, "end": 4, "sense_id": bloom.id}]
    assert published == [
        ("translation", None, None),
        ("judged", spans, None),
        ("done", None, "開く 뜻"),
    ]


def test_meanings_are_made_after_the_analysis_is_saved(client, fake_llm, gakusei):
    # 뜻 생성이 느리거나 실패해도 번역·문법·단어 위치는 이미 저장돼 있다.
    saved = []
    fake_llm.before_gloss = lambda: saved.append(SentenceAnalysis.objects.get().status)

    analyze(client, "私は学生です。")

    assert saved == ["complete"]


def test_meaning_still_missing_or_failed_is_sent_early_as_being_prepared(client, fake_llm, gakusei):
    gakusei.senses.update(meaning_status="failed")
    fake_llm.gloss_response = {"senses": []}

    response = analyze(client, "私は学生です。")

    # 이번 작업이 다시 만들므로 먼저 보낼 때는 실패가 아니라 준비 중이다.
    [early] = response.events[0]["words"]
    assert (early["sense"]["meaning_ko"], early["sense"]["meaning_status"]) == (None, "ai")
    # 다시 만들지 못했으면 저장한 결과에서 실패로 보인다.
    [word] = response.events[-1]["words"]
    assert word["sense"]["meaning_status"] == "failed"
