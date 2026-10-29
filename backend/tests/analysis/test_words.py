"""분석 API: 문장 단어를 JMdict에서 찾아 위치별 뜻으로 기록한다(#96)."""

import json

import pytest

from analysis import jobs
from analysis.models import SentenceAnalysis, WordSense
from tests.analysis.helpers import add_word, analyze, post, read_body, saved_analyses

pytestmark = pytest.mark.django_db


@pytest.fixture
def gakusei():
    """학생: 뜻이 하나라 LLM 없이 정해진다."""
    return add_word(3, ["学生"], ["がくせい"], [(["student"], [], None)])


@pytest.fixture
def hiraku():
    """開く(ひらく): 뜻이 둘이라 LLM이 고른다."""
    return add_word(
        6,
        ["開く"],
        ["ひらく"],
        [(["to open", "to undo", "to unseal", "to unpack"], ["transitive"], None)]
        + [(["to bloom"], ["intransitive"], None)],
        tags=("verb", "group1"),
    )


def sense(word, index):
    return word.senses.get(jmdict_sense_index=index)


def word_answer(token_id, sense_id):
    return {"token_id": token_id, "sense_id": sense_id}


def test_single_sense_word_is_recorded_without_asking_the_llm(client, fake_llm, gakusei):
    # 토큰: 0 私 / 1 は / 2 学生 / 3 です. 私는 사전에 없어 빠진다.
    fake_llm.response = {"translation_ko": "나는 학생입니다."}

    response = analyze(client, "私は学生です。")

    assert response.json()["words"] == [
        {
            "start": 2,
            "end": 4,
            "dictionary_form": "学生",
            "reading": "がくせい",
            "tags": ["noun"],
            "in_dictionary": True,
            "sense": {
                "tags": [],
                "gloss_en": ["student"],
                "origin": "jmdict",
                "status": "approved",
                "meaning_ko": "学生 뜻",
                "meaning_status": "ai",
            },
        }
    ]
    assert fake_llm.requests[0]["words"] == []
    row = SentenceAnalysis.objects.get()
    student = sense(gakusei, 1).id
    assert row.word_spans == [{"start": 2, "end": 4, "sense_id": student}]
    assert row.sense_ids == [student]


def test_same_word_in_other_sentences_points_at_the_same_sense(client, fake_llm, gakusei):
    analyze(client, "私は学生です。")
    analyze(client, "学生が来た。")

    first, second = SentenceAnalysis.objects.order_by("id")
    assert first.sense_ids == second.sense_ids == [sense(gakusei, 1).id]


def test_word_with_several_senses_is_chosen_by_the_llm(client, fake_llm, hiraku):
    # 토큰: 0 本 / 1 を / 2 開い / 3 た
    bloom = sense(hiraku, 2).id
    fake_llm.response = {"translation_ko": "책을 펼쳤다", "words": [word_answer(2, bloom - 1)]}

    response = analyze(client, "本を開いた")

    # 후보는 '뜻 ID: 영어 뜻 최대 3개' 모양이다.
    assert fake_llm.requests[0]["words"] == [
        {
            "token_id": 2,
            "candidates": [f"{bloom - 1}: to open; to undo; to unseal", f"{bloom}: to bloom"],
        }
    ]
    [word] = response.json()["words"]
    assert (word["start"], word["end"], word["dictionary_form"], word["reading"]) == (
        2,
        4,
        "開く",
        "ひらく",
    )
    assert word["tags"] == ["group1", "verb"]
    assert word["sense"]["tags"] == ["transitive"]
    assert SentenceAnalysis.objects.get().sense_ids == [bloom - 1]


@pytest.mark.parametrize(
    "answers",
    [
        [],  # 답이 빠짐
        [word_answer(2, 0)],  # 후보에 없는 ID
        [word_answer(2, "1")],
        [word_answer(0, None)],
        ["not an object"],
    ],
)
def test_wrong_sense_answer_drops_only_that_word(client, fake_llm, gakusei, hiraku, answers):
    # 토큰: 0 学生 / 1 が / 2 開い / 3 た
    fake_llm.response = {"translation_ko": "학생이 열었다", "words": answers}

    response = analyze(client, "学生が開いた")

    assert [w["dictionary_form"] for w in response.json()["words"]] == ["学生"]
    row = SentenceAnalysis.objects.get()
    assert row.translation_ko == "학생이 열었다"
    assert row.sense_ids == [sense(gakusei, 1).id]


def test_non_list_words_answer_fails(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다.", "words": None}

    response = analyze(client, "私は学生です。")

    assert response.json() == {"error": "ANALYSIS:FAILED"}
    assert saved_analyses().count() == 0


def test_same_word_twice_keeps_a_sense_for_each_place(client, fake_llm, hiraku):
    # 토큰: 0 開い / 1 て / 2 開い / 3 た
    open_, bloom = sense(hiraku, 1).id, sense(hiraku, 2).id
    fake_llm.response = {
        "translation_ko": "열고 피었다",
        "words": [word_answer(0, open_), word_answer(2, bloom)],
    }

    response = analyze(client, "開いて開いた")

    assert [(w["start"], w["sense"]["gloss_en"]) for w in response.json()["words"]] == [
        (0, ["to open", "to undo", "to unseal", "to unpack"]),
        (3, ["to bloom"]),
    ]
    row = SentenceAnalysis.objects.get()
    assert row.word_spans == [
        {"start": 0, "end": 2, "sense_id": open_},
        {"start": 3, "end": 5, "sense_id": bloom},
    ]
    assert sorted(row.sense_ids) == [open_, bloom]


def test_particles_and_numbers_are_not_looked_up(client, fake_llm):
    # は·3은 JMdict에 있어도 학습 단어가 아니다. 토큰: 0 3 / 1 人 / 2 は / 3 行く
    add_word(20, [], ["は"], [(["topic marker"], [], None)])
    add_word(21, ["3"], ["さん"], [(["three"], [], None)])
    fake_llm.response = {"translation_ko": "⟨N1⟩명은 간다"}

    response = analyze(client, "3人は行く")

    assert response.json()["words"] == []
    assert SentenceAnalysis.objects.get().sense_ids == []


def test_words_are_sent_before_the_llm_answers(client, fake_llm, gakusei, hiraku):
    # 토큰: 0 学生 / 1 が / 2 開い / 3 た
    fake_llm.response = {"translation_ko": "학생이 열었다"}
    response = post(client, "学生が開いた")
    # 앞선 이벤트는 응답을 만들 때 정해지고, LLM 작업은 스트림을 읽을 때 시작한다.
    assert fake_llm.requests == []

    first = json.loads(read_body(response).decode().splitlines()[0])

    assert first["type"] == "grammar"
    student, undecided = first["words"]
    assert student["sense"]["gloss_en"] == ["student"]
    # 뜻이 여럿이면 표제·읽기·태그만 보내고 뜻은 아직 없다.
    assert {key: undecided[key] for key in ("start", "end", "dictionary_form", "sense")} == {
        "start": 3,
        "end": 5,
        "dictionary_form": "開く",
        "sense": None,
    }


def test_word_of_several_entries_shows_all_readings_and_common_tags_before_choosing(
    client, fake_llm, hiraku
):
    # 開く: あく / ひらく는 다른 항목이다. 고르기 전에는 한 읽기로 단정하지 않는다.
    add_word(5, ["開く"], ["あく"], [(["to open (intr.)"], [], None)], tags=("verb",))
    response = post(client, "本を開いた")

    first = json.loads(read_body(response).decode().splitlines()[0])

    [word] = first["words"]
    assert (word["reading"], word["tags"], word["sense"]) == ("あく・ひらく", ["verb"], None)


def test_cached_sentence_returns_the_same_words(client, fake_llm, gakusei, hiraku):
    fake_llm.response = {
        "translation_ko": "학생이 열었다",
        "words": [word_answer(2, sense(hiraku, 1).id)],
    }
    first = analyze(client, "学生が開いた")

    second = analyze(client, "  学生が開いた。")

    assert len(fake_llm.requests) == 1
    shifted = [{**w, "start": w["start"] + 2, "end": w["end"] + 2} for w in first.json()["words"]]
    assert second.json()["words"] == shifted


def test_row_without_word_spans_is_analyzed_again(client, fake_llm, gakusei):
    analyze(client, "私は学生です。")
    SentenceAnalysis.objects.update(word_spans=None, sense_ids=None)

    response = analyze(client, "私は学生です。")

    assert len(fake_llm.requests) == 2
    assert [w["dictionary_form"] for w in response.json()["words"]] == ["学生"]
    assert SentenceAnalysis.objects.get().word_spans is not None


def test_rejected_sense_is_not_shown_from_cache(client, fake_llm, gakusei):
    analyze(client, "私は学生です。")
    WordSense.objects.update(sense_status="rejected")

    response = analyze(client, "私は学生です。")

    assert response.json()["words"] == []


def test_chosen_senses_are_sent_as_soon_as_the_words_section_closes(
    client, fake_llm, hiraku, monkeypatch
):
    # 단어 칸이 닫히면 새 구문 칸을 기다리지 않고 고른 뜻을 보낸다(#205).
    bloom = sense(hiraku, 2).id
    fake_llm.response = {"translation_ko": "책을 펼쳤다", "words": [word_answer(2, bloom)]}
    published = []
    original = jobs.publish

    def recording(sentence_hash, message):
        if message["type"] == "judged":
            published.append((fake_llm.result_given, message["word_spans"]))
        original(sentence_hash, message)

    monkeypatch.setattr(jobs, "publish", recording)

    response = analyze(client, "本を開いた")

    assert published == [(False, [{"start": 2, "end": 4, "sense_id": bloom}])]
    [judged] = (e for e in response.events if e["type"] == "judged")
    assert judged["words"][0]["sense"]["tags"] == ["intransitive"]
    assert SentenceAnalysis.objects.get().sense_ids == [bloom]
