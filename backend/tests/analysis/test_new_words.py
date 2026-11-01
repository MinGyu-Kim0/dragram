"""사전에 없는 단어를 두 단계로 만들기(#134).

1단계는 첫 LLM 요청에서 사전에 없는 토큰의 사전형·읽기를 받고, 2단계(word_gloss)는 서버가 다시
찾은 기존 후보에서 뜻을 고르거나 새 단어·뜻을 만든다.
"""

from unittest.mock import ANY

import pytest
from django.core import serializers

from analysis.models import ReviewStatus, SentenceAnalysis, UsageLog, Word, WordSense
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import add_word, analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

WORDS = "/admin/analysis/word/"
SENSES = "/admin/analysis/wordsense/"


def new_word(token_id, dictionary_form, reading):
    return {"token_id": token_id, "dictionary_form": dictionary_form, "reading": reading}


def defined(word_id, sense_id=None, meaning_ko="", sense_tags=(), word_tags=()):
    return {
        "word_id": word_id,
        "sense_id": sense_id,
        "meaning_ko": meaning_ko,
        "sense_tags": list(sense_tags),
        "word_tags": list(word_tags),
    }


def analyze_hashiru(client, fake_llm, **define):
    """토큰: 0 走っ / 1 て / 2 いる. 走る는 사전에 없다."""
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_words": [new_word(0, "走る", "ハシル")],
    }
    if define:
        fake_llm.define_response = {"words": [defined(0, **define)]}
    return analyze(client, "走っている")


def test_unknown_tokens_are_sent_but_proper_nouns_are_not(client, fake_llm):
    # 토큰: 0 田中 / 1 が / 2 走っ / 3 て / 4 いる. 田中는 SudachiPy 고유명사다.
    fake_llm.response = {"translation_ko": "다나카가 달리고 있다"}

    analyze(client, "田中が走っている")

    assert fake_llm.requests[0]["unknown_words"] == [2, 4]
    assert fake_llm.define_requests == []


def test_new_honorific_suffix_keeps_its_pos_and_unreviewed_meaning(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "니시야마 씨",
        "name_spans": [{"token_ids": [0, 1], "type": "person"}],
        "new_words": [new_word(1, "さん", "さん")],
    }
    fake_llm.define_response = {
        "words": [defined(0, meaning_ko="씨", sense_tags=["honorific"], word_tags=["suffix"])]
    }

    response = analyze(client, "西山さん")

    assert fake_llm.requests[0]["unknown_words"] == [1]
    person, suffix = response.json()["words"]
    assert person["dictionary_form"] == "西山"
    assert suffix["tags"] == ["suffix"]
    assert suffix["sense"]["tags"] == ["honorific"]
    assert suffix["sense"]["status"] == "pending"
    assert Word.objects.get().tags == ["suffix"]


def test_new_word_is_made_in_two_steps_and_shown_as_unreviewed(client, fake_llm):
    response = analyze_hashiru(
        client, fake_llm, meaning_ko="달리다", sense_tags=["intransitive"], word_tags=["verb"]
    )

    [request] = fake_llm.define_requests
    assert request == {
        "sentence": "走っている",
        "words": [
            {
                "word_id": 0,
                "token_id": 0,
                "dictionary_form": "走る",
                "reading": "はしる",
                "candidates": [],
            }
        ],
    }
    word = Word.objects.get()
    assert (word.dictionary_form, word.reading, word.jmdict_seq) == ("走る", "はしる", None)
    # 읽기도 표기로 둔다(JMdict처럼). 그래야 표기에 맞는 읽기를 고를 수 있다.
    assert (word.forms, word.readings, word.tags) == (["走る", "はしる"], ["はしる"], ["verb"])
    sense = word.senses.get()
    assert (sense.sense_origin, sense.sense_status) == ("llm", "pending")
    assert (sense.meaning_ko, sense.meaning_source, sense.meaning_status) == ("달리다", "llm", "ai")
    assert sense.tags == ["intransitive"]
    assert response.json()["words"] == [
        {
            "start": 0,
            "end": 2,
            "dictionary_form": "走る",
            "reading": "はしる",
            "tags": ["verb"],
            "in_dictionary": False,
            "sense": {
                "id": ANY,
                "tags": ["intransitive"],
                "gloss_en": [],
                "origin": "llm",
                "status": "pending",
                "meaning_ko": "달리다",
                "meaning_status": "ai",
            },
        }
    ]
    assert saved_words() == [{"start": 0, "end": 2, "sense_id": sense.pk}]
    assert list(UsageLog.objects.filter(kind="llm").values_list("purpose", flat=True)) == [
        "first_response",
        "word_gloss",
    ]


def saved_words():
    return SentenceAnalysis.objects.get(sentence_hash__isnull=False).word_spans


def test_made_word_is_found_like_a_dictionary_word_next_time(client, fake_llm):
    analyze_hashiru(client, fake_llm)
    fake_llm.forget_requests()
    # 토큰: 0 走っ / 1 た
    fake_llm.response = {"translation_ko": "달렸다"}

    response = analyze(client, "走った")

    assert fake_llm.requests[0]["unknown_words"] == []
    assert fake_llm.define_requests == []
    assert response.json()["words"][0]["sense"]["meaning_ko"] == "走る 뜻"


@pytest.fixture
def honoru():
    """사전에는 있지만 SudachiPy 사전형(走る)으로는 못 찾는 단어: 奔る(はしる)."""
    return add_word(9, ["奔る"], ["はしる"], [(["to run"], [], None)], tags=("verb", "group1"))


def answer_honoru(client, fake_llm, **define):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_words": [new_word(0, "奔る", "はしる")],
    }
    fake_llm.define_response = {"words": [defined(0, **define)]}
    return analyze(client, "走っている")


def test_found_again_word_offers_its_senses_to_choose(client, fake_llm, honoru):
    run = honoru.senses.get()

    answer_honoru(client, fake_llm, sense_id=run.pk)

    [request] = fake_llm.define_requests
    assert request["words"][0]["candidates"] == [f"{run.pk}: to run"]
    assert saved_words() == [{"start": 0, "end": 2, "sense_id": run.pk}]
    assert Word.objects.count() == 1 and WordSense.objects.count() == 1


def test_chosen_dictionary_sense_without_korean_meaning_gets_one(client, fake_llm, honoru):
    run = honoru.senses.get()

    answer_honoru(client, fake_llm, sense_id=run.pk)

    [asked] = fake_llm.gloss_requests
    assert [sense["sense_id"] for sense in asked] == [run.pk]
    assert WordSense.objects.get(pk=run.pk).meaning_ko == "奔る 뜻"


def test_found_again_word_without_fitting_sense_gets_an_unreviewed_sense(client, fake_llm, honoru):
    answer_honoru(client, fake_llm, meaning_ko="내달리다", sense_tags=["intransitive"])

    added = honoru.senses.get(sense_origin="llm")
    assert (added.sense_status, added.meaning_ko, added.jmdict_sense_index) == (
        "pending",
        "내달리다",
        None,
    )
    assert added.tags == ["intransitive"]
    assert saved_words() == [{"start": 0, "end": 2, "sense_id": added.pk}]
    assert Word.objects.count() == 1


def test_same_new_word_made_meanwhile_keeps_one_word_row(client, fake_llm):
    def made_by_another_job():
        word = Word.objects.create(
            dictionary_form="走る",
            reading="はしる",
            forms=["走る", "はしる"],
            readings=["はしる"],
            is_common=False,
            pos="",
            tags=["verb"],
        )
        WordSense.objects.create(
            word=word,
            tags=[],
            sense_origin="llm",
            sense_status="pending",
            meaning_ko="뛰다",
            meaning_source="llm",
            meaning_status="ai",
        )

    fake_llm.before_define = made_by_another_job

    analyze_hashiru(client, fake_llm, meaning_ko="달리다")

    word = Word.objects.get()
    # 진 쪽은 기존 단어를 쓰고 뜻은 따로 판단해 더한다.
    assert sorted(word.senses.values_list("meaning_ko", flat=True)) == ["달리다", "뛰다"]
    assert saved_words() == [
        {"start": 0, "end": 2, "sense_id": word.senses.get(meaning_ko="달리다").pk}
    ]


@pytest.mark.parametrize(
    "answer",
    [
        new_word(0, "走る", ""),
        new_word(0, "", "はしる"),
        new_word(0, "走る", "走る"),
        new_word(0, "走2る", "はしる"),
        # 토큰(走っ)보다 훨씬 긴 답은 문장 조각일 수 있다.
        new_word(0, "走っている人", "はしっているひと"),
        # 사전에서 찾은 토큰이나 받지 않은 토큰
        new_word(1, "て", "て"),
        {"token_id": "0", "dictionary_form": "走る", "reading": "はしる"},
    ],
)
def test_invalid_first_step_answer_drops_only_that_word(client, fake_llm, answer):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_words": [answer]}

    response = analyze(client, "走っている")

    assert response.json()["translation_ko"] == "달리고 있다"
    assert fake_llm.define_requests == []
    assert not Word.objects.exists()
    assert saved_words() == []


@pytest.mark.parametrize("reading", ["ー", "ゝ", "ヽ"])
def test_reading_without_kana_drops_only_that_word(client, fake_llm, reading):
    kare = add_word(4, ["彼"], ["かれ"], [(["he"], [], None)], tags=("pronoun",))
    fake_llm.response = {
        "translation_ko": "그가 달리고 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"))],
        "new_words": [new_word(2, "走る", reading)],
    }

    response = analyze(client, "彼が走っている").json()

    assert response["translation_ko"] == "그가 달리고 있다"
    assert len(response["grammar"]) == 1
    assert response["grammar"][0]["review_status"] == "pending"
    assert [word["dictionary_form"] for word in response["words"]] == ["彼"]
    assert not Word.objects.exclude(pk=kare.pk).exists()
    assert saved_words() == [{"start": 0, "end": 1, "sense_id": kare.senses.get().pk}]


def test_same_token_answered_twice_in_first_step_is_dropped(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_words": [new_word(0, "走る", "はしる"), new_word(0, "奔る", "はしる")],
    }

    analyze(client, "走っている")

    assert fake_llm.define_requests == []


@pytest.mark.parametrize(
    "define",
    [
        {"words": [defined(0, meaning_ko=" ")]},
        {"words": [defined(0, meaning_ko="⟨N1⟩명")]},
        {"words": [defined(0, sense_id=999)]},
        {"words": [defined(1, meaning_ko="달리다")]},
        {"words": []},
        {"words": [defined(0, meaning_ko="달리다"), defined(0, meaning_ko="뛰다")]},
        "not an object",
    ],
)
def test_invalid_second_step_answer_drops_only_that_word(client, fake_llm, define):
    fake_llm.response = {
        "translation_ko": "그가 달리고 있다",
        "new_words": [new_word(2, "走る", "はしる")],
    }
    fake_llm.define_response = define

    # 토큰: 0 彼 / 1 が / 2 走っ / 3 て / 4 いる. 彼는 사전 단어다.
    kare = add_word(4, ["彼"], ["かれ"], [(["he"], [], None)], tags=("pronoun",))
    response = analyze(client, "彼が走っている")

    assert response.json()["translation_ko"] == "그가 달리고 있다"
    assert not Word.objects.exclude(pk=kare.pk).exists()
    assert saved_words() == [{"start": 0, "end": 1, "sense_id": kare.senses.get().pk}]


def test_second_step_failure_drops_new_words_but_keeps_the_analysis(client, fake_llm):
    fake_llm.define_error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    response = analyze_hashiru(client, fake_llm)

    assert response.json()["translation_ko"] == "달리고 있다"
    assert not Word.objects.exists()
    assert saved_words() == []


def test_tags_outside_the_allowed_list_are_not_stored(client, fake_llm):
    analyze_hashiru(
        client,
        fake_llm,
        meaning_ko="달리다",
        sense_tags=["intransitive", "verb", "made-up"],
        word_tags=["verb", "transitive", "made-up"],
    )

    word = Word.objects.get()
    assert word.tags == ["verb"]
    assert word.senses.get().tags == ["intransitive"]


def test_public_tables_get_no_sentence_text(client, fake_llm):
    # 원문 그대로가 키 텍스트가 되지 않게 감싼다.
    analyze_hashiru(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "그는 달리고 있다",
        "new_words": [new_word(2, "走る", "はしる")],
    }
    analyze(client, "「彼は走っている」")

    for model in (Word, WordSense):
        dumped = serializers.serialize("json", model.objects.all())
        assert "走っている" not in dumped
        assert "彼は" not in dumped


def made_word(admin_client, client, fake_llm):
    analyze_hashiru(client, fake_llm, meaning_ko="달리다")
    return Word.objects.get(jmdict_seq__isnull=True)


def word_form(word, **changes):
    sense = word.senses.get()
    return {
        "dictionary_form": word.dictionary_form,
        "reading": word.reading,
        "senses-TOTAL_FORMS": 1,
        "senses-INITIAL_FORMS": 1,
        "senses-0-id": sense.pk,
        "senses-0-word": word.pk,
        "senses-0-meaning_ko": sense.meaning_ko,
        **changes,
    }


def test_admin_edits_form_and_reading_of_a_made_word(admin_client, client, fake_llm):
    word = made_word(admin_client, client, fake_llm)

    response = admin_client.post(
        f"{WORDS}{word.pk}/change/", word_form(word, dictionary_form=" 奔る ", reading="ハシル")
    )

    assert response.status_code == 302
    word.refresh_from_db()
    assert (word.dictionary_form, word.reading) == ("奔る", "はしる")
    assert (word.forms, word.readings) == (["奔る", "はしる"], ["はしる"])


@pytest.mark.parametrize("changes", [{"dictionary_form": " "}, {"reading": "走る"}])
def test_admin_rejects_empty_or_non_kana_values(admin_client, client, fake_llm, changes):
    word = made_word(admin_client, client, fake_llm)

    response = admin_client.post(f"{WORDS}{word.pk}/change/", word_form(word, **changes))

    assert response.status_code == 200
    word.refresh_from_db()
    assert (word.dictionary_form, word.reading) == ("走る", "はしる")


def test_admin_cannot_make_two_made_words_the_same(admin_client, client, fake_llm):
    word = made_word(admin_client, client, fake_llm)
    Word.objects.create(
        dictionary_form="奔る",
        reading="はしる",
        forms=["奔る", "はしる"],
        readings=["はしる"],
        is_common=False,
        pos="",
        tags=[],
    )

    response = admin_client.post(
        f"{WORDS}{word.pk}/change/", word_form(word, dictionary_form="奔る")
    )

    assert response.status_code == 200
    assert Word.objects.get(pk=word.pk).dictionary_form == "走る"


def test_admin_cannot_edit_form_of_a_dictionary_word(admin_client, honoru):
    sense = honoru.senses.get()
    admin_client.post(
        f"{WORDS}{honoru.pk}/change/",
        {
            "dictionary_form": "바뀜",
            "reading": "ばし",
            "senses-TOTAL_FORMS": 1,
            "senses-INITIAL_FORMS": 1,
            "senses-0-id": sense.pk,
            "senses-0-word": honoru.pk,
            "senses-0-meaning_ko": "",
        },
    )

    honoru.refresh_from_db()
    assert (honoru.dictionary_form, honoru.reading) == ("奔る", "はしる")


def run_sense_action(admin_client, action, *senses):
    return admin_client.post(
        SENSES, {"action": action, "_selected_action": [sense.pk for sense in senses]}
    )


def test_admin_approves_and_rejects_llm_senses_only(admin_client, client, fake_llm, honoru):
    made = made_word(admin_client, client, fake_llm).senses.get()
    dictionary = honoru.senses.get()

    run_sense_action(admin_client, "approve_senses", made, dictionary)
    assert WordSense.objects.get(pk=made.pk).sense_status == ReviewStatus.APPROVED

    run_sense_action(admin_client, "reject_senses", made, dictionary)
    assert WordSense.objects.get(pk=made.pk).sense_status == ReviewStatus.REJECTED
    assert WordSense.objects.get(pk=dictionary.pk).sense_status == ReviewStatus.APPROVED

    run_sense_action(admin_client, "unreject_senses", made)
    assert WordSense.objects.get(pk=made.pk).sense_status == ReviewStatus.PENDING


def test_rejected_llm_sense_is_left_out_of_the_response(admin_client, client, fake_llm):
    made = made_word(admin_client, client, fake_llm).senses.get()
    run_sense_action(admin_client, "reject_senses", made)

    response = analyze(client, "走っている")

    assert response.json()["words"] == []


def test_senses_cannot_be_added_or_deleted_in_admin(admin_client, client, fake_llm):
    made = made_word(admin_client, client, fake_llm).senses.get()

    assert admin_client.get(f"{SENSES}add/").status_code == 403
    assert admin_client.get(f"{SENSES}{made.pk}/delete/").status_code == 403


def test_new_sense_quoting_the_whole_sentence_is_not_stored(client, fake_llm):
    analyze_hashiru(client, fake_llm, meaning_ko="달리다 (走っている)")

    assert not WordSense.objects.exists()
    assert saved_words() == []


def test_new_word_quoting_the_whole_sentence_is_not_asked_or_stored(client, fake_llm):
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_words": [new_word(0, "走っている", "はしっている")],
    }

    analyze(client, "走っている")

    assert fake_llm.define_requests == []
    assert not Word.objects.exists()


def test_second_step_runs_after_the_grammar_is_asked_again(client, fake_llm):
    # 토큰: 0 走っ / 1 て / 2 いる. ている를 등록해 둔다.
    fake_llm.response = {
        "translation_ko": "달리고 있다",
        "new_patterns": [new_pattern((1, "lemma"), (2, "lemma"), example_ja="走っている")],
    }
    analyze(client, "走っている")
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる. 같은 조건의 새 구문은 다시 묻는다.
    fake_llm.response = {
        "translation_ko": "그가 와 있다",
        "new_patterns": [new_pattern((3, "lemma"), (4, "lemma"), usage_name="결과")],
        "new_words": [new_word(2, "来る", "くる")],
    }
    fake_llm.rejudge_response = {"spans": [span_answer(0, "usage", 1)]}
    asked_before = []
    fake_llm.before_define = lambda: asked_before.append(len(fake_llm.rejudge_requests))

    analyze(client, "彼が来ている")

    assert asked_before == [1]
    assert Word.objects.filter(dictionary_form="来る").exists()
