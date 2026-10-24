"""JMdict XML 파서(design-decisions 24절). 원본은 읽기만 하고 보관하지 않는다.

JMdict는 품사·태그를 DTD 엔티티(&v1; 등)로 쓴다. 그대로 파싱하면 엔티티가 설명문으로
풀리므로, 줄마다 엔티티 참조를 코드 이름으로 바꾼 뒤 스트림으로 읽는다.
"""

import re
from dataclasses import dataclass
from typing import NamedTuple
from xml.etree.ElementTree import XMLPullParser

# 흔한 단어 표시(ke_pri·re_pri). JMdict가 흔한 단어로 보는 값들이다.
COMMON_PRIORITIES = {"news1", "ichi1", "spec1", "spec2", "gai1"}

_GROUP1 = ("v5aru", "v5b", "v5g", "v5k", "v5k-s", "v5m", "v5n", "v5r", "v5r-i", "v5s")
_GROUP1 += ("v5t", "v5u", "v5u-s", "v5uru")
# 예외 1그룹: 모양은 2그룹(-いる·-える)인데 1그룹인 동사(帰る 등). JMdict에서는 일반
# 5단과 같은 v5r이라 읽기 모양을 함께 본다(design-decisions 48절).
_LOOKS_GROUP2 = re.compile(r"[いきしちにひみりぎじぢびぴぃゐえけせてねへめれげぜでべぺぇゑ]る$")

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
GROUP1_EXCEPTION = "group1_exception"

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

# 단어 전체 태그. word.tags에는 검색용 뜻 태그도 함께 모으므로 응답할 때 이것으로 가른다.
WHOLE_WORD_TAGS = frozenset(
    {tag for tags in WORD_TAGS.values() for tag in tags} | {GROUP1_EXCEPTION}
)

# 뜻 태그(검색용으로 word.tags에도 모은다)
SENSE_TAG_NAMES = frozenset(SENSE_TAGS.values()) | {LOANWORD}

# 태그 허용 목록
ALLOWED_TAGS = WHOLE_WORD_TAGS | set(SENSE_TAGS.values()) | {LOANWORD}

# XML 기본 엔티티는 그대로 두고 나머지 엔티티 참조만 코드 이름으로 바꾼다.
_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)([\w-]+);")
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
# word의 varchar 칸 길이
MAX_LENGTH = 255


class JMdictError(ValueError):
    """스키마에 넣을 수 없는 항목. 메시지에 항목 번호를 담는다."""


class _Kanji(NamedTuple):
    keb: str
    priorities: list


class _Kana(NamedTuple):
    reb: str
    priorities: list
    # re_restr: 이 읽기를 쓰는 표기(비면 모든 표기)
    restrictions: list
    # re_nokanji: 한자 표기에 쓰지 않는 읽기
    no_kanji: bool


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
    parser = XMLPullParser(events=("start", "end"))
    root = None
    for line in lines:
        parser.feed(_ENTITY.sub(r"\1", line))
        for event, element in parser.read_events():
            if event == "start":
                root = element if root is None else root
            elif element.tag == "entry":
                yield _entry(element)
                # 읽은 항목은 루트에서 떼어 메모리에 쌓이지 않게 한다.
                root.clear()
    parser.close()


def _texts(element, path):
    return [child.text for child in element.findall(path)]


def _unique(items):
    return list(dict.fromkeys(items))


def _display_reading(dictionary_form, kana, has_kanji):
    """대표 읽기: 한자 표기가 있으면 대표 표기에 쓰는 첫 읽기, 없으면 첫 읽기."""
    if has_kanji:
        for k in kana:
            if not k.no_kanji and (not k.restrictions or dictionary_form in k.restrictions):
                return k.reb
    return kana[0].reb


def _entry(element):
    seq = element.findtext("ent_seq")
    kanji = [_Kanji(k.findtext("keb"), _texts(k, "ke_pri")) for k in element.findall("k_ele")]
    kana = [
        _Kana(
            r.findtext("reb"),
            _texts(r, "re_pri"),
            _texts(r, "re_restr"),
            r.find("re_nokanji") is not None,
        )
        for r in element.findall("r_ele")
    ]
    forms = [k.keb for k in kanji]
    rebs = [k.reb for k in kana]
    if not seq or not rebs or not all(forms + rebs) or element.find("sense") is None:
        raise JMdictError(f"항목 {seq}: 번호·표기·읽기·뜻 중 빈 것이 있음")
    restrictions = {
        k.reb: [] if k.no_kanji else k.restrictions for k in kana if k.no_kanji or k.restrictions
    }
    dictionary_form = forms[0] if forms else rebs[0]
    reading = _display_reading(dictionary_form, kana, bool(forms))

    # word.pos는 첫 뜻의 pos 코드다.
    senses, word_tags, sense_pos, first_pos, all_pos = [], [], [], [], set()
    for index, sense in enumerate(element.findall("sense"), start=1):
        # pos가 없는 뜻은 앞 뜻의 pos를 이어받는다(JMdict 규약).
        sense_pos = _texts(sense, "pos") or sense_pos
        first_pos = first_pos or sense_pos
        all_pos.update(sense_pos)
        tags = [SENSE_TAGS[c] for c in sense_pos + _texts(sense, "misc") if c in SENSE_TAGS]
        if sense.find("lsource") is not None:
            tags.append(LOANWORD)
        word_tags += [tag for code in sense_pos for tag in WORD_TAGS.get(code, ())] + tags
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

    readings = _unique(to_hiragana(reb) for reb in rebs)
    if "v5r" in all_pos and any(_LOOKS_GROUP2.search(r) for r in readings):
        word_tags = [GROUP1_EXCEPTION if tag == "group1" else tag for tag in word_tags]
    pos = ",".join(first_pos)
    if max(len(dictionary_form), len(reading), len(pos)) > MAX_LENGTH:
        raise JMdictError(f"항목 {seq}: 대표 표기·읽기·품사가 {MAX_LENGTH}자를 넘음")
    return Entry(
        seq=int(seq),
        dictionary_form=dictionary_form,
        reading=reading,
        forms=_unique(forms + rebs),
        readings=readings,
        is_common=any(set(k.priorities) & COMMON_PRIORITIES for k in [*kanji, *kana]),
        reading_restrictions=restrictions or None,
        pos=pos,
        tags=sorted(set(word_tags)),
        senses=senses,
    )
