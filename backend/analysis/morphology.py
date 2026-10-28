import threading
from functools import cache
from typing import NamedTuple

from sudachipy import Dictionary, SplitMode
from sudachipy.errors import SudachiError

from errors import AnalysisError, BusinessError

_local = threading.local()


@cache
def _dictionary():
    # core 사전 (요구사항 9장). 사전은 무거워서 프로세스에서 하나만 연다.
    return Dictionary(dict="core")


def _tokenizer():
    # Tokenizer는 동시에 쓸 수 없어서 스레드마다 따로 만든다.
    if not hasattr(_local, "tokenizer"):
        _local.tokenizer = _dictionary().tokenizer(mode=SplitMode.C)
    return _local.tokenizer


class Morpheme(NamedTuple):
    # 위치는 코드포인트 기준 [begin, end)
    begin: int
    end: int
    # 품사 대분류(名詞, 助詞 등)
    pos: str
    # SudachiPy 추정 읽기(가타카나). 사전에 없는 말은 표기 그대로일 수 있다. 수사로 시작하는
    # 말은 Sentence가 JMdict 읽기(히라가나)로 바꿔 둘 수 있다(#271).
    reading: str
    # 패턴 조건에 쓰는 표제어. 조사·조동사는 원형(축약형 보존), 내용어는 정규형(표기 통일)
    lemma: str
    # 품사 중분류와 활용형. 없으면(*) None
    pos2: str | None
    conjugation_form: str | None
    # 품사 소분류(固有名詞 아래 地名 등). 없으면(*) None. 판별 규칙 조건에만 쓰고 패턴 조건에는
    # 넣지 않는다(#55).
    pos3: str | None = None
    # 사전형(SudachiPy dictionary_form, 표기는 원문 그대로)과 활용 여부(활용형 칸이 있는가).
    # 단어 찾기에 쓴다(#96).
    dictionary_form: str = ""
    conjugates: bool = False


FUNCTION_POS = {"助詞", "助動詞"}

# 탁음화 조건부 규칙: 1그룹 동사 음편형 뒤에서 탁음이 된 기능어는 청음형 lemma로 본다
# (読んでしまう는 てしまう 패턴). だら는 원형이 だ라 だ → た로 함께 처리된다. ないで처럼 그 밖의
# で는 그대로 두어 별개 패턴이 된다. 조사·조동사는 원형을 쓰므로 SudachiPy가 ちゃ를 て로 바꾸는
# 정규화는 따르지 않는다. 회화체 どく·じまう·でく·じゃ(接続助詞)도 같다(#63). 飲んどいた는
# SudachiPy가 ど + 居る로 나눠 맞추지 못한다(알려진 한계).
_UNVOICED = {
    "で": "て",
    "でる": "てる",
    "じゃう": "ちゃう",
    "だ": "た",
    "どく": "とく",
    "じまう": "ちまう",
    "でく": "てく",
    "じゃ": "ちゃ",
}
# 음편형 중 탁음화를 일으키는 것(促音便 뒤는 원래 청음이다: 走って). イ音便은 1그룹 동사에만 있다.
_VOICING_FORMS = {"連用形-撥音便", "連用形-イ音便"}


def _after_sound_change(prev, morph):
    if prev.pos != "動詞" or prev.conjugation_form not in _VOICING_FORMS:
        return morph
    if morph.pos not in FUNCTION_POS or morph.lemma not in _UNVOICED:
        return morph
    return morph._replace(lemma=_UNVOICED[morph.lemma])


def _morpheme(m):
    pos = m.part_of_speech()
    lemma = m.dictionary_form() if pos[0] in FUNCTION_POS else m.normalized_form()
    pos2, pos3, conjugation_form = (
        None if value == "*" else value for value in (pos[1], pos[2], pos[5])
    )
    return Morpheme(
        m.begin(),
        m.end(),
        pos[0],
        m.reading_form(),
        lemma,
        pos2,
        conjugation_form,
        pos3,
        m.dictionary_form(),
        pos[4] != "*",
    )


def morphemes(text):
    """문장을 형태소(Morpheme)로 나눈다.

    SudachiPy가 나누지 못하는 입력(49,149바이트 초과 등)은 ANALYSIS:FAILED다.
    """
    try:
        tokens = _tokenizer().tokenize(text)
    except SudachiError as e:
        raise BusinessError(AnalysisError.FAILED, "형태소 분석 실패") from e
    # SudachiPy는 입력을 내부에서 바꿔(… → ...) 길이 0인 형태소를 덧붙이기도 한다. 원문에
    # 대응하는 글자가 없어 구간을 만들 수 없으므로 뺀다.
    morphs = [_morpheme(m) for m in tokens if m.begin() < m.end()]
    return morphs[:1] + [
        _after_sound_change(p, m) for p, m in zip(morphs, morphs[1:], strict=False)
    ]
