"""문장 단어를 JMdict(word·word_sense)에서 찾는다(requirements '단어 사전과 단어 매칭', #96).

활용하지 않는 단어는 표기 + 읽기로, 활용하는 단어는 사전형 표기로 찾는다(SudachiPy 읽기는
활용형 읽기라 食べた의 食べ는 タベ다). 가나로 쓴 단어는 읽기(히라가나로 통일)로도 찾고, 못 찾으면
정규형·표층형으로 한 번 더 찾는다. 읽기→표기 제한과 뜻→표기·읽기 제한은 후보를 거르고 표기에
맞는 읽기를 고르는 데만 쓴다.
"""

import re
from typing import NamedTuple

from django.db.models import Prefetch, Q

from analysis.jmdict import WHOLE_WORD_TAGS, to_hiragana
from analysis.models import ReviewStatus, Word, WordSense

# 가나(장음 ー, 반복 부호 포함)로만 쓴 말. 가타카나 블록의 문장부호(・ ゠)는 가나가 아니다.
_KANA = re.compile(r"[ぁ-ゖゝゞァ-ヺー-ヾㇰ-ㇿ]+")


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
    return bool(_KANA.fullmatch(text))


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
    # 정규형(morph.lemma)·표층형으로 다시 찾을 때는 표기만 맞춘다.
    again = [
        _Query(value, to_hiragana(value) if is_kana(value) else None)
        for value in dict.fromkeys((morph.lemma, surface))
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


def lookup(text, morphs, tokens):
    """토큰(순번)마다 후보 뜻. {토큰: [Candidate]}이고 못 찾은 토큰은 빠진다.

    text는 형태소 분석한 분석 텍스트다. 흔한 단어를 앞에 두고, 그다음 JMdict 번호·뜻 순서다.
    반려된 뜻은 후보가 아니다.
    """
    senses = Prefetch(
        "senses",
        queryset=WordSense.objects.exclude(sense_status=ReviewStatus.REJECTED).order_by(
            "jmdict_sense_index", "id"
        ),
    )
    found = {}
    for token in tokens:
        for query in _queries(text, morphs[token]):
            words = (
                Word.objects.filter(_filter(query))
                .prefetch_related(senses)
                .order_by("-is_common", "jmdict_seq", "id")
            )
            candidates = _candidates(words, query)
            if candidates:
                found[token] = candidates
                break
    return found


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


def word_tags(word):
    """단어 전체 태그(word.tags에 함께 모은 검색용 뜻 태그는 뺀다)."""
    return sorted(set(word.tags) & WHOLE_WORD_TAGS)


def response_item(start, end, word, reading, sense):
    """응답의 단어 항목. sense가 None이면 뜻을 아직 고르지 않은 것이다(LLM 응답 전).

    태그는 단어 전체 태그와 고른 뜻의 태그다. 뜻은 출처·검수 상태와 한국어 뜻(#97 전에는 NULL)
    까지 실어, 미검수가 검수처럼 보이지 않게 화면이 이 값으로 표시를 정한다.
    """
    return {
        "start": start,
        "end": end,
        "dictionary_form": word.dictionary_form,
        "reading": reading,
        "tags": word_tags(word),
        "sense": None
        if sense is None
        else {
            "tags": sense.tags,
            "gloss_en": sense.gloss_en or [],
            "origin": sense.sense_origin,
            "status": sense.sense_status,
            "meaning_ko": sense.meaning_ko,
            "meaning_status": sense.meaning_status,
        },
    }


def llm_candidates(candidates):
    """LLM에 넘길 후보: '뜻 ID: 영어 뜻 최대 3개'."""
    return [f"{c.sense.id}: {'; '.join((c.sense.gloss_en or [])[:3])}" for c in candidates]
