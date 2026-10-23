"""JMdict 파서(#95). DB 없이 표본 XML만 읽는다."""

from pathlib import Path

from analysis.jmdict import Entry, Sense, parse

SAMPLE = Path(__file__).parent / "data" / "jmdict_sample.xml"


def entries():
    with SAMPLE.open(encoding="utf-8") as f:
        return {entry.seq: entry for entry in parse(f)}


def test_entry_with_kanji_form_takes_its_first_form_and_reading():
    assert entries()[1358280] == Entry(
        seq=1358280,
        dictionary_form="食べる",
        reading="たべる",
        forms=["食べる", "たべる"],
        readings=["たべる"],
        is_common=True,
        reading_restrictions=None,
        pos="v1,vt",
        tags=["group2", "transitive", "verb"],
        senses=[
            # 영어 뜻만 둔다. pos가 없는 뜻은 앞 뜻의 pos를 이어받는다.
            Sense(index=1, gloss_en=["to eat"], tags=["transitive"], applies_to=None),
            Sense(
                index=2,
                gloss_en=["to live on (e.g. a salary)", "to live off"],
                tags=["transitive"],
                applies_to=None,
            ),
        ],
    )


def test_kana_only_entry_unifies_readings_to_hiragana_and_keeps_the_display_reading():
    entry = entries()[1049180]

    assert (entry.dictionary_form, entry.reading) == ("コーヒー", "コーヒー")
    assert entry.forms == ["コーヒー"]
    assert entry.readings == ["こーひー"]
    assert entry.is_common
    assert entry.tags == ["loanword", "noun"]
    assert entry.senses[0].tags == ["loanword"]


def test_sense_restrictions_and_transitivity_stay_with_each_sense():
    entry = entries()[1202450]

    assert not entry.is_common
    assert entry.reading == "あく"
    assert [(s.applies_to, s.tags) for s in entry.senses] == [
        ({"readings": ["あく"]}, ["intransitive"]),
        ({"readings": ["ひらく"]}, ["transitive"]),
    ]
    # 단어 태그는 뜻 태그까지 합친다(검색용).
    assert entry.tags == ["group1", "intransitive", "transitive", "verb"]


def test_reading_restrictions_pick_the_first_reading_allowed_for_the_display_form():
    entry = entries()[1576260]

    # 첫 표기 朔日에는 いちにち를 쓰지 않으므로 ついたち가 대표 읽기다.
    assert (entry.dictionary_form, entry.reading) == ("朔日", "ついたち")
    assert entry.forms == ["朔日", "一日", "いちにち", "ついたち", "ツイタチ"]
    assert entry.readings == ["いちにち", "ついたち"]
    # 한자 표기에 쓰지 않는 읽기(re_nokanji)는 빈 목록이다.
    assert entry.reading_restrictions == {"いちにち": ["一日"], "ツイタチ": []}
    assert entry.is_common
    assert entry.senses[0].applies_to == {"forms": ["一日"], "readings": ["いちにち"]}
    assert entry.senses[1].applies_to is None


def test_misc_codes_become_sense_tags_and_unknown_codes_are_left_out():
    entry = entries()[1009760]

    assert entry.pos == "v5aru,vi"
    assert entry.senses[0].tags == ["honorific", "intransitive", "uk"]
    assert entry.senses[0].gloss_en == ["to come & to go (honorific)"]
    # exp·arch는 변환표에 없다.
    assert entry.senses[1].tags == []
    assert entry.tags == ["group1", "honorific", "intransitive", "tricky", "uk", "verb"]
