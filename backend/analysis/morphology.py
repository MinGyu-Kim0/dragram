import threading
from functools import cache

from sudachipy import Dictionary, SplitMode

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


def tokenize(text):
    """문장을 형태소로 나누고, LLM이 가리킬 수 있게 순서대로 ID를 매긴다."""
    return [{"id": i, "surface": m.surface()} for i, m in enumerate(_tokenizer().tokenize(text))]
