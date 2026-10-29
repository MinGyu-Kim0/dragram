"""문장 단어를 JMdict(word·word_sense)에서 찾는다(requirements '단어 사전과 단어 매칭', #96).

활용하지 않는 단어는 표기 + 읽기로, 활용하는 단어는 사전형 표기로 찾는다(SudachiPy 읽기는
활용형 읽기라 食べた의 食べ는 タベ다). 가나로 쓴 단어는 읽기(히라가나로 통일)로도 찾고, 못 찾으면
정규형·표층형(활용하는 단어는 정규형만)으로 한 번 더 찾는다. 읽기→표기 제한과 뜻→표기·읽기
제한은 후보를 거르고 표기에 맞는 읽기를 고르는 데만 쓴다.
"""

import re
from typing import NamedTuple

from django.db.models import Prefetch, Q

from analysis.jmdict import WHOLE_WORD_TAGS, to_hiragana
from analysis.models import ReviewStatus, Word, WordSense
from analysis.morphology import morphemes

# 가나(장음 ー, 반복 부호 포함)로만 쓴 말. 가타카나 블록의 문장부호(・ ゠)는 가나가 아니다.
_KANA = re.compile(r"[ぁ-ゖゝゞァ-ヺー-ヾㇰ-ㇿ]+")
# 한자 수사 글자
_KANJI_NUMERAL = re.compile(r"[〇一二三四五六七八九十百千万億兆]")


class Candidate(NamedTuple):
    # 후보 뜻(word를 함께 읽어 둔다)
    sense: WordSense
    # 이 토큰의 표기에 맞는 그 단어의 읽기(보일 값)
    reading: str


class _Query(NamedTuple):
    # 찾을 표기와, 알면 그 읽기(히라가나). 활용하는 한자 표기는 읽기를 모른다.
    form: str
    reading: str | None


def is_kana(text):
    # 장음·반복 부호만으로는 읽기가 될 수 없다.
    return bool(_KANA.fullmatch(text) and text.strip("ーゝゞヽヾ"))


def _queries(text, morph):
    """토큰 하나를 찾을 차례(앞의 것으로 못 찾으면 다음 것으로 찾는다)."""
    surface = text[morph.begin : morph.end]
    form = morph.dictionary_form if morph.conjugates else surface
    if is_kana(form):
        first = _Query(form, to_hiragana(form))
    elif morph.conjugates:
        first = _Query(form, None)
    else:
        first = _Query(form, to_hiragana(morph.reading))
    # 정규형(morph.lemma)·표층형으로 다시 찾을 때는 표기만 맞춘다. 활용형 표층(する의 し)은
    # 다른 단어(氏)와 같은 가나일 수 있어 찾지 않는다(#201).
    values = (morph.lemma,) if morph.conjugates else (morph.lemma, surface)
    again = [
        _Query(value, to_hiragana(value) if is_kana(value) else None)
        for value in dict.fromkeys(values)
    ]
    return [first, *again]


def _filter(query):
    if is_kana(query.form):
        return Q(forms__contains=[query.form]) | Q(readings__contains=[query.reading])
    found = Q(forms__contains=[query.form])
    if query.reading is not None:
        found &= Q(readings__contains=[query.reading])
    return found


def _allowed_readings(word, query):
    """그 표기로 쓸 수 있는 읽기(히라가나). 원래 읽기 하나라도 허용하면 허용한다.

    읽기 제한(reading_restrictions)의 열쇠는 원래 표기(가타카나일 수 있다)라, word.forms에 함께
    든 원래 읽기로 맞춘다. 가나로 쓴 토큰은 그 가나가 곧 읽기다.
    """
    if is_kana(query.form):
        return {query.reading} & set(word.readings)
    restrictions = word.reading_restrictions or {}
    allowed = {
        to_hiragana(reb)
        for reb in word.forms
        if to_hiragana(reb) in word.readings
        and (reb not in restrictions or query.form in restrictions[reb])
    }
    if query.reading is not None:
        allowed &= {query.reading}
    return allowed


def _sense_readings(sense, query, allowed):
    """그 뜻으로 쓸 수 있는 읽기. 뜻이 이 표기에 쓰이지 않으면 빈 집합이다."""
    applies_to = sense.applies_to or {}
    forms = applies_to.get("forms")
    # 표기 제한(stagk)은 한자 표기 사이의 제한이라 가나로 쓴 토큰에는 걸지 않는다.
    if forms and not is_kana(query.form) and query.form not in forms:
        return set()
    readings = applies_to.get("readings")
    if readings:
        return allowed & {to_hiragana(r) for r in readings}
    return allowed


def _display_reading(word, query, readings):
    """보일 읽기. 가나로 쓴 토큰은 그 표기를, 아니면 대표 읽기나 원래 읽기 중 허용된 것을 쓴다."""
    if is_kana(query.form):
        return query.form
    rebs = [word.reading, *(reb for reb in word.forms if to_hiragana(reb) in word.readings)]
    return next(reb for reb in rebs if to_hiragana(reb) in readings)


def _candidates(words, query):
    found = []
    for word in words:
        allowed = _allowed_readings(word, query)
        for sense in word.senses.all():
            readings = _sense_readings(sense, query, allowed)
            if readings:
                found.append(Candidate(sense, _display_reading(word, query, readings)))
    return found


def _jmdict_reading(form, reading):
    """JMdict에서 그 표기로 쓰는 읽기 가운데 보일 것. reading(히라가나)이 그 하나면 그대로,
    아니면 흔한 단어·JMdict 순서의 첫 읽기다. 그 표기가 JMdict에 없으면 None이다. LLM이 만든
    단어(jmdict_seq 없음)는 근거로 쓰지 않는다.
    """
    query = _Query(form, None)
    found = Word.objects.filter(jmdict_seq__isnull=False, forms__contains=[form]).order_by(
        "-is_common", "jmdict_seq"
    )
    readings = [r for word in found for r in word.readings if r in _allowed_readings(word, query)]
    if not readings:
        return None
    return reading if reading in readings else readings[0]


def fixed_morphemes(text):
    """SudachiPy 형태소에서 수사로 시작하는 말의 경계와 읽기를 JMdict로 바로잡은 것(#271).
    분석과 패턴 확인(예문·검수)이 같은 토큰을 보도록 형태소는 모두 여기서 받는다.

    SudachiPy는 一件을 一 + 件으로 나누고, 한 단어로 묶은 一回도 イチカイ처럼 소리 변화 없이
    읽는다. 수사 + 바로 뒤 명사·접미사(조수사)를 이은 표기가 JMdict에 있으면 한 명사로 합치고,
    활용하지 않는 토큰이 수사 글자로 시작하면(一緒처럼 수사가 아닌 말도) JMdict 읽기로 맞춘다.
    고친 읽기는 히라가나다.
    아라비아 숫자는 자리표시자로 바뀌어 학습 단어가 아니므로 건드리지 않는다.
    """
    morphs = morphemes(text)
    fixed = []
    i = 0
    while i < len(morphs):
        m = morphs[i]
        i += 1
        surface = text[m.begin : m.end]
        if m.conjugates or not _KANJI_NUMERAL.match(surface):
            fixed.append(m)
            continue
        after = morphs[i] if i < len(morphs) else None
        if m.pos2 == "数詞" and after is not None and after.pos in {"名詞", "接尾辞"}:
            joined = text[m.begin : after.end]
            reading = _jmdict_reading(joined, to_hiragana(m.reading + after.reading))
            if reading is not None:
                fixed.append(
                    m._replace(
                        end=after.end,
                        pos2="普通名詞",
                        pos3=None,
                        reading=reading,
                        lemma=joined,
                        dictionary_form=joined,
                    )
                )
                i += 1
                continue
        reading = _jmdict_reading(surface, to_hiragana(m.reading))
        fixed.append(m if reading is None else m._replace(reading=reading))
    return fixed


def lookup(text, morphs, tokens):
    """토큰(순번)마다 후보 뜻. {토큰: [Candidate]}이고 못 찾은 토큰은 빠진다.

    text는 형태소 분석한 분석 텍스트다. 흔한 단어를 앞에 두고, 그다음 JMdict 번호·뜻 순서다.
    반려된 뜻은 후보가 아니다.
    """
    found = {}
    for token in tokens:
        for query in _queries(text, morphs[token]):
            candidates = _find(query)
            if candidates:
                found[token] = candidates
                break
    return found


def _find(query):
    senses = Prefetch(
        "senses",
        queryset=WordSense.objects.exclude(sense_status=ReviewStatus.REJECTED).order_by(
            "jmdict_sense_index", "id"
        ),
    )
    words = (
        Word.objects.filter(_filter(query))
        .prefetch_related(senses)
        .order_by("-is_common", "jmdict_seq", "id")
    )
    return _candidates(words, query)


def find_again(form, reading):
    """LLM이 답한 사전형·읽기(히라가나)로 다시 찾은 후보 뜻(#134 2단계)."""
    return _find(_Query(form, to_hiragana(form) if is_kana(form) else reading))


def add_llm_sense(word, meaning, tags):
    """LLM이 만든 미검수 뜻을 단어 아래에 더한다(한국어 뜻 포함, #134)."""
    return WordSense.objects.create(
        word=word,
        tags=tags,
        sense_origin=WordSense.Origin.LLM,
        sense_status=ReviewStatus.PENDING,
        meaning_ko=meaning,
        meaning_source=WordSense.MeaningSource.LLM,
        meaning_status=WordSense.MeaningStatus.AI,
    )


def get_or_make_word(form, reading, tags):
    """사전에 없는 단어(jmdict_seq 없음). (사전형, 읽기)가 같은 단어가 있으면 그 행을 쓴다.

    동시에 만들면 부분 유일 제약으로 하나만 남는다. 대표 표기는 처음 저장한 값으로 고정된다.
    읽기도 표기에 넣어(JMdict처럼) 표기에 맞는 읽기를 고를 수 있게 한다.
    """
    word, _ = Word.objects.get_or_create(
        jmdict_seq=None,
        dictionary_form=form,
        reading=reading,
        defaults={
            "forms": list(dict.fromkeys([form, reading])),
            "readings": [reading],
            "is_common": False,
            "pos": "",
            "tags": tags,
        },
    )
    return word


def reading_for(sense, text, morph):
    """저장된 뜻을 이 토큰으로 보일 때의 읽기. 찾을 때와 같은 차례로 맞춰 본다.

    형태소 경계가 달라 토큰을 모르면(morph가 None) 그 단어의 대표 읽기다.
    """
    word = sense.word
    for query in _queries(text, morph) if morph is not None else ():
        readings = _sense_readings(sense, query, _allowed_readings(word, query))
        if readings:
            return _display_reading(word, query, readings)
    return word.reading


def word_tags(word, morph=None):
    """단어 전체 태그(word.tags에 함께 모은 검색용 뜻 태그는 뺀다)."""
    tags = set(word.tags) & WHOLE_WORD_TAGS
    # 공용 단어의 명사 태그가 이 문장에서 접미사로 쓰인 자리까지 명사로 보이게 하지 않는다.
    if morph is not None and morph.pos == "接尾辞":
        tags = (tags - {"noun", "proper_noun"}) | {"suffix"}
    return sorted(tags)


def response_item(start, end, word, reading, sense, before_save=False, *, morph=None):
    """응답의 단어 항목. sense가 None이면 뜻을 아직 고르지 않은 것이다(LLM 응답 전).

    before_save는 분석을 저장하기 전에 보내는 항목이다. 한국어 뜻이 없는 뜻은 이 작업이 만들므로
    지난번에 실패했어도 실패로 보이지 않는다(화면은 '뜻을 준비하는 중', #97).

    태그는 단어 전체 태그와 고른 뜻의 태그다. 뜻은 출처·검수 상태와 한국어 뜻(#97 전에는 NULL)
    까지 실어, 미검수가 검수처럼 보이지 않게 화면이 이 값으로 표시를 정한다.
    """
    return {
        "start": start,
        "end": end,
        "dictionary_form": word.dictionary_form,
        "reading": reading,
        "tags": word_tags(word, morph),
        # 사전(JMdict) 단어인가. 화면은 사전 단어가 있을 때만 JMdict 출처 각주를 단다(#134).
        "in_dictionary": word.jmdict_seq is not None,
        "sense": None
        if sense is None
        else {
            "tags": sense.tags,
            "gloss_en": sense.gloss_en or [],
            "origin": sense.sense_origin,
            "status": sense.sense_status,
            "meaning_ko": sense.meaning_ko,
            "meaning_status": WordSense.MeaningStatus.AI
            if before_save and sense.meaning_ko is None
            else sense.meaning_status,
        },
    }


def missing_meanings(sense_ids):
    """그 뜻들 가운데 한국어 뜻이 없는 뜻(생성 실패 포함, id 순서)."""
    return list(
        WordSense.objects.filter(pk__in=sense_ids, meaning_ko__isnull=True)
        .select_related("word")
        .order_by("id")
    )


def gloss_input(sense):
    """word_gloss에 넘길 뜻 하나. 근거는 사전 칸뿐이고 문장은 넣지 않는다(#97)."""
    return {
        "sense_id": sense.id,
        "dictionary_form": sense.word.dictionary_form,
        "reading": sense.word.reading,
        "pos": sense.word.pos,
        "gloss_en": sense.gloss_en or [],
        "tags": sense.tags,
    }


def save_meanings(asked, made):
    """만든 한국어 뜻을 저장하고, 요청했지만 만들지 못한 뜻은 생성 실패로 둔다.

    아직 한국어 뜻이 없는 뜻만 쓰는 조건부 UPDATE라, 그사이 다른 작업이나 관리자가 저장한 값을
    덮지 않는다.
    """
    for sense_id, meaning in made.items():
        WordSense.objects.filter(pk=sense_id, meaning_ko__isnull=True).update(
            meaning_ko=meaning,
            meaning_source=WordSense.MeaningSource.LLM,
            meaning_status=WordSense.MeaningStatus.AI,
        )
    WordSense.objects.filter(pk__in=set(asked) - set(made), meaning_ko__isnull=True).update(
        meaning_status=WordSense.MeaningStatus.FAILED
    )


def llm_candidates(candidates):
    """LLM에 넘길 후보: '뜻 ID: 영어 뜻 최대 3개'."""
    # LLM이 만든 뜻은 영어 뜻이 없어 한국어 뜻을 보인다(#134).
    return [
        f"{c.sense.id}: {'; '.join((c.sense.gloss_en or [c.sense.meaning_ko or ''])[:3])}"
        for c in candidates
    ]
