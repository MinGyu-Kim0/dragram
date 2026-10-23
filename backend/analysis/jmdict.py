"""JMdict XML 파서(design-decisions 24절). 원본은 읽기만 하고 보관하지 않는다.

JMdict는 품사·태그를 DTD 엔티티(&v1; 등)로 쓴다. 그대로 파싱하면 엔티티가 설명문으로
풀리므로, 줄마다 엔티티 참조를 코드 이름으로 바꾼 뒤 스트림으로 읽는다.
"""

import re
from dataclasses import dataclass
from xml.etree.ElementTree import XMLPullParser

# 흔한 단어 표시(ke_pri·re_pri). JMdict가 흔한 단어로 보는 값들이다.
COMMON_PRIORITIES = {"news1", "ichi1", "spec1", "spec2", "gai1"}

_GROUP1 = ("v5aru", "v5b", "v5g", "v5k", "v5k-s", "v5m", "v5n", "v5r", "v5r-i", "v5s")
_GROUP1 += ("v5t", "v5u", "v5u-s", "v5uru")
# 예외 활용: 불규칙 동사와 특수 활용 동사, いい
_TRICKY = {"v5aru", "v5k-s", "v5r-i", "v5u-s", "v5uru", "v1-s", "vk", "vs-i", "vs-s", "vz"}
_TRICKY |= {"adj-ix"}

# 단어 전체 태그(requirements '태그 분리'): JMdict pos 코드 → 태그. 여기에 없는 코드는
# 태그로 옮기지 않는다(word.pos에는 남는다).
WORD_TAGS = {
    **{code: ("noun",) for code in ("n", "n-adv", "n-t", "n-pref", "n-suf")},
    "n-pr": ("noun", "proper_noun"),
    "pn": ("pronoun",),
    **{code: ("verb", "group1") for code in _GROUP1},
    **{code: ("verb", "group2") for code in ("v1", "v1-s")},
    **{code: ("verb", "group3") for code in ("vk", "vs-i", "vs-s", "vz")},
    **{code: ("i_adjective",) for code in ("adj-i", "adj-ix")},
    "adj-na": ("na_adjective",),
    **{code: ("adverb",) for code in ("adv", "adv-to")},
    "adj-pn": ("adnominal",),
    "conj": ("conjunction",),
    "int": ("interjection",),
}
for _code in _TRICKY:
    WORD_TAGS[_code] = (*WORD_TAGS[_code], "tricky")

# 뜻마다 다른 태그: JMdict pos·misc 코드 → 태그. lsource가 있는 뜻은 loanword다.
SENSE_TAGS = {
    "vt": "transitive",
    "vi": "intransitive",
    "hon": "honorific",
    "hum": "humble",
    "pol": "polite",
    "uk": "uk",
    "on-mim": "onomatopoeia",
}
LOANWORD = "loanword"

# 태그 허용 목록
ALLOWED_TAGS = frozenset(
    {tag for tags in WORD_TAGS.values() for tag in tags} | set(SENSE_TAGS.values()) | {LOANWORD}
)

# XML 기본 엔티티는 그대로 두고 나머지 엔티티 참조만 코드 이름으로 바꾼다.
_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)([\w-]+);")
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


@dataclass(frozen=True)
class Sense:
    index: int
    gloss_en: list
    tags: list
    applies_to: dict | None


@dataclass(frozen=True)
class Entry:
    seq: int
    dictionary_form: str
    reading: str
    forms: list
    readings: list
    is_common: bool
    reading_restrictions: dict | None
    pos: str
    tags: list
    senses: list


def to_hiragana(text):
    """가타카나(ァ~ヶ)를 히라가나로 바꾼다. 장음 부호 등 나머지는 그대로 둔다."""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def parse(lines):
    """JMdict XML 줄들에서 항목을 하나씩 낸다."""
    parser = XMLPullParser(events=("end",))
    for line in lines:
        parser.feed(_ENTITY.sub(r"\1", line))
        for _, element in parser.read_events():
            if element.tag == "entry":
                yield _entry(element)
                element.clear()
    parser.close()


def _texts(element, path):
    return [child.text for child in element.findall(path)]


def _unique(items):
    return list(dict.fromkeys(items))


def _entry(element):
    kanji = [(k.findtext("keb"), _texts(k, "ke_pri")) for k in element.findall("k_ele")]
    kana = [
        (
            r.findtext("reb"),
            _texts(r, "re_pri"),
            _texts(r, "re_restr"),
            r.find("re_nokanji") is not None,
        )
        for r in element.findall("r_ele")
    ]
    forms = [keb for keb, _ in kanji]
    rebs = [reb for reb, *_ in kana]
    restrictions = {
        reb: [] if nokanji else restr for reb, _, restr, nokanji in kana if nokanji or restr
    }
    dictionary_form = forms[0] if forms else rebs[0]
    reading = rebs[0]
    if forms:
        reading = next(
            (
                reb
                for reb, _, restr, nokanji in kana
                if not nokanji and (not restr or dictionary_form in restr)
            ),
            rebs[0],
        )

    # word.pos는 첫 뜻의 pos 코드다.
    senses, word_tags, pos, first_pos = [], [], [], []
    for index, sense in enumerate(element.findall("sense"), start=1):
        # pos가 없는 뜻은 앞 뜻의 pos를 이어받는다(JMdict 규약).
        pos = _texts(sense, "pos") or pos
        first_pos = first_pos or pos
        tags = [SENSE_TAGS[c] for c in pos + _texts(sense, "misc") if c in SENSE_TAGS]
        if sense.find("lsource") is not None:
            tags.append(LOANWORD)
        word_tags += [tag for code in pos for tag in WORD_TAGS.get(code, ())] + tags
        applies_to = {
            key: values
            for key, values in (
                ("forms", _texts(sense, "stagk")),
                ("readings", _texts(sense, "stagr")),
            )
            if values
        }
        senses.append(
            Sense(
                index=index,
                gloss_en=[
                    g.text for g in sense.findall("gloss") if g.get(_XML_LANG, "eng") == "eng"
                ],
                tags=sorted(set(tags)),
                applies_to=applies_to or None,
            )
        )

    return Entry(
        seq=int(element.findtext("ent_seq")),
        dictionary_form=dictionary_form,
        reading=reading,
        forms=_unique(forms + rebs),
        readings=_unique(to_hiragana(reb) for reb in rebs),
        is_common=any(
            set(pri) & COMMON_PRIORITIES
            for pri in [pri for _, pri in kanji] + [pri for _, pri, *_ in kana]
        ),
        reading_restrictions=restrictions or None,
        pos=",".join(first_pos),
        tags=sorted(set(word_tags)),
        senses=senses,
    )
