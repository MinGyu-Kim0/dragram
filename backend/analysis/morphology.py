from functools import cache

from sudachipy import Dictionary, SplitMode


@cache
def _tokenizer():
    # core 사전, 분할 모드 C (요구사항 9장)
    return Dictionary(dict="core").tokenizer(mode=SplitMode.C)


def tokenize(text):
    """문장을 형태소로 나누고, LLM이 가리킬 수 있게 순서대로 ID를 매긴다."""
    return [{"id": i, "surface": m.surface()} for i, m in enumerate(_tokenizer().tokenize(text))]
