"""문장 단어를 JMdict(word·word_sense)에서 찾는다(#96). 실제 JMdict 대신 표본 행을 쓴다."""

import pytest

from analysis import words
from analysis.jmdict import to_hiragana
from analysis.models import ReviewStatus, Word, WordSense
from analysis.morphology import morphemes

pytestmark = pytest.mark.django_db


def add_word(seq, kanji, kana, senses, restrictions=None, common=True, tags=("noun",)):
    """표본 단어. senses는 (영어 뜻 목록, 뜻 태그, applies_to)들이다."""
    word = Word.objects.create(
        dictionary_form=(kanji or kana)[0],
        reading=kana[0],
        forms=[*kanji, *kana],
        readings=list(dict.fromkeys(to_hiragana(k) for k in kana)),
        is_common=common,
        reading_restrictions=restrictions,
        pos="n",
        tags=list(tags),
        jmdict_seq=seq,
    )
    for index, (gloss, sense_tags, applies_to) in enumerate(senses, start=1):
        WordSense.objects.create(
            word=word,
            jmdict_sense_index=index,
            gloss_en=gloss,
            tags=list(sense_tags),
            applies_to=applies_to,
            sense_origin=WordSense.Origin.JMDICT,
            sense_status=ReviewStatus.APPROVED,
            meaning_status=WordSense.MeaningStatus.AI,
        )
    return word


def lookup(text):
    """토큰 순번 → [(단어 jmdict_seq, 뜻 번호, 보일 읽기)]. 학습 단어가 아닌 토큰도 넘긴다."""
    morphs = morphemes(text)
    found = words.lookup(text, morphs, range(len(morphs)))
    return {
        token: [(c.sense.word.jmdict_seq, c.sense.jmdict_sense_index, c.reading) for c in cands]
        for token, cands in found.items()
    }


def test_conjugated_verb_is_found_by_dictionary_form():
    add_word(1, ["食べる"], ["たべる"], [(["to eat"], [], None)], tags=("verb", "group2"))

    # 토큰: 0 食べ / 1 た. SudachiPy 읽기(タベ)는 활용형 읽기라 쓰지 않는다.
    assert lookup("食べた") == {0: [(1, 1, "たべる")]}


def test_kana_written_word_is_found_by_reading():
    add_word(1, ["食べる"], ["たべる"], [(["to eat"], [], None)], tags=("verb", "group2"))

    assert lookup("たべる") == {0: [(1, 1, "たべる")]}


def test_katakana_loanword_keeps_its_katakana_reading():
    add_word(2, [], ["コーヒー"], [(["coffee"], ["loanword"], None)])

    # 토큰: 0 コーヒー / 1 を / 2 飲む
    assert lookup("コーヒーを飲む") == {0: [(2, 1, "コーヒー")]}


def test_uninflected_kanji_word_needs_matching_reading():
    # 표기가 같아도 읽기가 다른 항목은 후보가 아니다.
    add_word(3, ["学生"], ["がくせい"], [(["student"], [], None)])
    add_word(4, ["学生"], ["がくしょう"], [(["Heian-period student"], [], None)])

    # 토큰: 0 学生 / 1 です
    assert lookup("学生です") == {0: [(3, 1, "がくせい")]}


def test_every_entry_of_a_conjugated_form_is_a_candidate():
    # 開く: あく / ひらく는 다른 항목이다. 활용형 읽기로는 고르지 않는다.
    add_word(5, ["開く"], ["あく"], [(["to open (intr.)"], ["intransitive"], None)])
    add_word(6, ["開く"], ["ひらく"], [(["to open"], [], None), (["to bloom"], [], None)])

    # 토큰: 0 開い / 1 た
    assert lookup("開いた") == {0: [(5, 1, "あく"), (6, 1, "ひらく"), (6, 2, "ひらく")]}


def test_common_entries_come_first():
    add_word(7, ["開く"], ["ひらく"], [(["to open"], [], None)], common=False)
    add_word(8, ["開く"], ["あく"], [(["to open (intr.)"], [], None)])

    assert lookup("開いた") == {0: [(8, 1, "あく"), (7, 1, "ひらく")]}


def test_reading_and_sense_restrictions_filter_candidates():
    # いちにち는 一日에만, さくじつ는 朔日에만 쓴다. 첫 뜻은 いちにち로 읽을 때만이다.
    add_word(
        9,
        ["一日", "朔日"],
        ["いちにち", "さくじつ"],
        [
            (["one day"], [], {"readings": ["いちにち"]}),
            (["first day of the month"], [], None),
            (["(written) 朔日 only"], [], {"forms": ["一日"]}),
        ],
        restrictions={"いちにち": ["一日"], "さくじつ": ["朔日"]},
    )

    # 토큰: 0 朔日 / 1 に / 2 会う
    assert lookup("朔日に会う") == {0: [(9, 2, "さくじつ")]}


def test_kanji_word_with_other_reading_is_found_again_by_normalized_form():
    # SudachiPy 읽기(ワタクシ)가 사전 읽기와 달라도, 정규형으로 한 번 더 찾는다.
    add_word(10, ["私"], ["わたし"], [(["I; me"], [], None)], tags=("pronoun",))

    # 토큰: 0 私 / 1 が / 2 行く
    assert lookup("私が行く") == {0: [(10, 1, "わたし")]}


def test_unknown_token_has_no_candidates():
    add_word(1, ["食べる"], ["たべる"], [(["to eat"], [], None)], tags=("verb", "group2"))

    assert lookup("飲む") == {}


def test_rejected_sense_is_not_a_candidate():
    word = add_word(6, ["開く"], ["ひらく"], [(["to open"], [], None), (["to bloom"], [], None)])
    word.senses.filter(jmdict_sense_index=2).update(sense_status=ReviewStatus.REJECTED)

    assert lookup("開いた") == {0: [(6, 1, "ひらく")]}
