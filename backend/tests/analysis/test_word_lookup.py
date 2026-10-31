"""문장 단어를 JMdict(word·word_sense)에서 찾는다(#96). 실제 JMdict 대신 표본 행을 쓴다."""

import pytest

from analysis import words
from analysis.models import ReviewStatus
from analysis.morphology import morphemes
from tests.analysis.helpers import add_word

pytestmark = pytest.mark.django_db


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


def test_conjugated_form_is_not_found_again_by_its_surface():
    # する가 사전에 없으면 연용형 し를 표층 가나로 찾아 읽기가 같은 氏에 잇지 않는다(#201).
    add_word(11, ["氏"], ["し"], [(["Mr"], [], None)])

    # 토큰: 0 出向 / 1 し / 2 た
    assert lookup("出向した") == {}


def test_unknown_token_has_no_candidates():
    add_word(1, ["食べる"], ["たべる"], [(["to eat"], [], None)], tags=("verb", "group2"))

    assert lookup("飲む") == {}


def test_rejected_sense_is_not_a_candidate():
    word = add_word(6, ["開く"], ["ひらく"], [(["to open"], [], None), (["to bloom"], [], None)])
    word.senses.filter(jmdict_sense_index=2).update(sense_status=ReviewStatus.REJECTED)

    assert lookup("開いた") == {0: [(6, 1, "ひらく")]}


def test_potential_form_also_offers_its_normalized_verb():
    # SudachiPy: 行ける는 사전형 行ける, 정규형 行く인 토큰 하나다. 가능형이면 行く의 뜻이 맞아
    # 두 단어의 뜻을 모두 후보로 둔다(#275).
    add_word(12, ["行ける"], ["いける"], [(["to be good (at)"], [], None)])
    add_word(13, ["行く"], ["いく", "ゆく"], [(["to go"], [], None)])

    # 토큰: 0 どこ / 1 まで / 2 も / 3 行ける
    assert lookup("どこまでも行ける")[3] == [(12, 1, "いける"), (13, 1, "いく")]


def test_same_word_by_dictionary_and_normalized_form_is_offered_once():
    # 사전형과 정규형이 같은 단어로 찾아지면(표기만 다름) 후보가 늘지 않는다.
    add_word(14, ["行う", "行なう"], ["おこなう"], [(["to perform"], [], None)])

    morphs = morphemes("行なう")
    assert (morphs[0].dictionary_form, morphs[0].lemma) == ("行なう", "行う")
    assert lookup("行なう") == {0: [(14, 1, "おこなう")]}
