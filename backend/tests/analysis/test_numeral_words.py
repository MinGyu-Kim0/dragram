"""분석 API: 수사+조수사를 JMdict 표기로 한 단어로 보고 JMdict 읽기를 쓴다(#271)."""

import pytest

from analysis import review
from analysis.patterns import Condition
from tests.analysis.helpers import add_word, analyze

pytestmark = pytest.mark.django_db


@pytest.fixture
def ken():
    return add_word(30, ["件"], ["けん"], [(["matter"], [], None)])


def test_numeral_and_counter_in_jmdict_are_one_word(client, fake_llm, ken):
    # SudachiPy: この / 一(イチ) / 件(ケン) / で
    add_word(31, ["一"], ["いち"], [(["one"], [], None)])
    add_word(32, ["一件"], ["いっけん"], [(["one matter"], [], None)])

    body = analyze(client, "この一件で").json()

    assert [(w["start"], w["end"], w["dictionary_form"], w["reading"]) for w in body["words"]] == [
        (2, 4, "一件", "いっけん")
    ]
    assert body["ruby"] == [{"start": 2, "end": 4, "reading": "いっけん"}]


def test_numeral_word_reading_follows_jmdict(client, fake_llm):
    # SudachiPy는 一回를 한 단어로 묶지만 읽기를 イチカイ로 낸다.
    add_word(33, ["一回"], ["いっかい"], [(["once"], [], None)])

    body = analyze(client, "一回").json()

    assert [(w["dictionary_form"], w["reading"]) for w in body["words"]] == [("一回", "いっかい")]
    assert body["ruby"] == [{"start": 0, "end": 2, "reading": "いっかい"}]


def test_numeral_and_counter_not_in_jmdict_stay_apart(client, fake_llm, ken):
    body = analyze(client, "十件").json()

    assert [w["dictionary_form"] for w in body["words"]] == ["件"]
    assert body["ruby"] == [
        {"start": 0, "end": 1, "reading": "じゅう"},
        {"start": 1, "end": 2, "reading": "けん"},
    ]


def test_word_made_by_the_llm_does_not_change_the_reading(client, fake_llm, ken):
    # jmdict_seq가 없는 단어(LLM이 만든 미검수 단어)는 읽기 근거로 쓰지 않는다.
    add_word(None, ["十件"], ["とおけん"], [(["ten matters"], [], None)])

    body = analyze(client, "十件").json()

    assert body["ruby"][0] == {"start": 0, "end": 1, "reading": "じゅう"}


def test_pattern_check_sees_the_same_numeral_word(ken):
    # 예문·검수의 패턴 확인도 분석과 같은 합친 토큰을 본다.
    add_word(32, ["一件"], ["いっけん"], [(["one matter"], [], None)])

    assert review.matches([Condition("一件", "名詞", "普通名詞", None)], "この一件で")
