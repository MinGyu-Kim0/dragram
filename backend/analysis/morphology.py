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
    # SudachiPy 추정 읽기(가타카나). 사전에 없는 말은 표기 그대로일 수 있다.
    reading: str


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
    return [
        Morpheme(m.begin(), m.end(), m.part_of_speech()[0], m.reading_form())
        for m in tokens
        if m.begin() < m.end()
    ]
