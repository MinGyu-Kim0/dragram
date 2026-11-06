"""사전에 없는 단어의 2단계(#134)와 저장 뒤 한국어 뜻 만들기(#97)."""

import pytest

from analysis import llm
from analysis.models import ReviewStatus, WordSense
from analysis.sentence import Sentence
from analysis.word_definitions import define_new_words, make_meanings
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import add_word

pytestmark = pytest.mark.django_db

TEXT = "走っている"
HASHIRU = {0: ("走る", "はしる")}


def still_current():
    return False


def defined(sense_id=None, meaning_ko="달리다"):
    return {
        "word_id": 0,
        "sense_id": sense_id,
        "meaning_ko": meaning_ko,
        "sense_tags": [],
        "word_tags": [],
    }


@pytest.fixture
def llm_client(fake_llm):
    return llm.get_client(lambda **_: None)


def test_word_not_in_the_dictionary_gets_a_new_unreviewed_sense(fake_llm, llm_client):
    fake_llm.define_response = {"words": [defined()]}

    chosen = define_new_words(Sentence(TEXT), llm_client, HASHIRU, still_current)

    sense = WordSense.objects.get(pk=chosen[0])
    assert (sense.word.dictionary_form, sense.word.reading) == ("走る", "はしる")
    assert (sense.meaning_ko, sense.sense_status) == ("달리다", ReviewStatus.PENDING)


def test_answer_can_pick_a_sense_of_the_word_found_again(fake_llm, llm_client):
    word = add_word(1, ["走る"], ["はしる"], [(["to run"], [], None)])
    existing = WordSense.objects.get(word=word)
    fake_llm.define_response = {"words": [defined(sense_id=existing.id, meaning_ko=None)]}

    chosen = define_new_words(Sentence(TEXT), llm_client, HASHIRU, still_current)

    assert chosen == {0: existing.id}
    assert WordSense.objects.count() == 1


def test_no_new_words_means_no_call(fake_llm, llm_client):
    assert define_new_words(Sentence(TEXT), llm_client, {}, still_current) == {}
    assert fake_llm.define_requests == []


def test_job_whose_result_will_be_dropped_does_not_ask(fake_llm, llm_client):
    chosen = define_new_words(Sentence(TEXT), llm_client, HASHIRU, lambda: True)

    assert chosen == {}
    assert fake_llm.define_requests == []


def test_failed_call_leaves_the_words_out_and_does_not_fail_the_analysis(fake_llm, llm_client):
    fake_llm.define_error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    assert define_new_words(Sentence(TEXT), llm_client, HASHIRU, still_current) == {}


def test_meaning_quoting_the_whole_sentence_is_not_stored(fake_llm, llm_client):
    fake_llm.define_response = {"words": [defined(meaning_ko=TEXT)]}

    assert define_new_words(Sentence(TEXT), llm_client, HASHIRU, still_current) == {}
    assert not WordSense.objects.exists()


def test_form_quoting_the_whole_sentence_is_not_asked(fake_llm, llm_client):
    quoted = {0: (TEXT, "はしっている")}

    assert define_new_words(Sentence(TEXT), llm_client, quoted, still_current) == {}
    assert fake_llm.define_requests == []


def test_missing_korean_meanings_are_made_in_one_call(fake_llm, llm_client):
    cat = WordSense.objects.get(word=add_word(1, ["猫"], ["ねこ"], [(["cat"], [], None)]))
    dog = WordSense.objects.get(word=add_word(2, ["犬"], ["いぬ"], [(["dog"], [], None)]))

    make_meanings(llm_client, [cat.id, dog.id])

    cat.refresh_from_db()
    dog.refresh_from_db()
    assert (cat.meaning_ko, dog.meaning_ko) == ("猫 뜻", "犬 뜻")
    assert len(fake_llm.gloss_requests) == 1


def test_senses_that_already_have_a_meaning_are_not_asked(fake_llm, llm_client):
    sense = WordSense.objects.get(word=add_word(1, ["猫"], ["ねこ"], [(["cat"], [], None)]))
    WordSense.objects.filter(pk=sense.pk).update(meaning_ko="고양이")

    make_meanings(llm_client, [sense.id])

    assert fake_llm.gloss_requests == []


def test_failed_call_marks_the_meanings_as_failed(fake_llm, llm_client):
    sense = WordSense.objects.get(word=add_word(1, ["猫"], ["ねこ"], [(["cat"], [], None)]))
    fake_llm.gloss_error = BusinessError(AnalysisError.FAILED, "LLM 호출 실패")

    make_meanings(llm_client, [sense.id])

    sense.refresh_from_db()
    assert (sense.meaning_ko, sense.meaning_status) == (None, WordSense.MeaningStatus.FAILED)
