"""문장 정규화. 규칙과 순서는 docs/requirements.md "정규화 규칙" 표를 따른다.

1단계(루비 제거)는 확장이 원문을 보낼 때 이미 했다. 서버는 2단계부터 한다.
규칙을 바꾸면 NORMALIZE_VERSION을 올린다.
"""

import re
import unicodedata

NORMALIZE_VERSION = 1

_HALFWIDTH_KANA = re.compile(r"[\uFF61-\uFF9F]+")
_SPACE = re.compile(r"\s+")
_LATIN = re.compile(r"[A-Za-z0-9]")
_TILDE = re.compile(r"[~〜～]")
_WRAPPING_PAIRS = {
    "「": "」",
    "『": "』",
    "（": "）",
    "(": ")",
    "【": "】",
    "〈": "〉",
    "《": "》",
    "“": "”",
    "‘": "’",
    '"': '"',
    "'": "'",
}
# 뜻을 바꾸는 기호. 나머지 기호는 지운다.
_MEANINGFUL_SYMBOLS = set("!?！？…‥")


def _unify_width(text):
    """2단계: 전각 영숫자는 반각으로, 반각 가나는 전각으로. NFKC 전체는 적용하지 않는다."""
    chars = []
    for ch in text:
        code = ord(ch)
        is_fullwidth_alnum = (
            0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A
        )
        chars.append(chr(code - 0xFEE0) if is_fullwidth_alnum else ch)
    # 반각 가나는 뒤따르는 반각 탁점·반탁점과 합쳐야 해서(ｶﾞ → ガ) 그 범위에만 NFKC를 쓴다.
    return _HALFWIDTH_KANA.sub(lambda m: unicodedata.normalize("NFKC", m.group()), "".join(chars))


def _remove_spaces(text):
    """3단계: 일본어 문자 사이 공백은 지우고, 영어 단어 사이는 공백 하나만 남긴다."""

    def replace(match):
        before = match.string[match.start() - 1 : match.start()]
        after = match.string[match.end() : match.end() + 1]
        return " " if _LATIN.fullmatch(before) and _LATIN.fullmatch(after) else ""

    return _SPACE.sub(replace, text.strip())


def _remove_tildes(text):
    """4단계: 물결표를 지운다."""
    return _TILDE.sub("", text)


def _wraps_whole(text, opening, closing):
    """맨 앞 괄호가 맨 끝에서 닫히는가. 「a」「b」처럼 중간에 닫히면 감싼 것이 아니다."""
    inner = text[1:-1]
    if opening == closing:
        return opening not in inner
    depth = 0
    for ch in inner:
        depth += (ch == opening) - (ch == closing)
        if depth < 0:
            return False
    return depth == 0


def _remove_wrapping(text):
    """5단계: 문장 전체를 감싼 바깥 괄호·따옴표만 지운다."""
    while len(text) >= 2:
        closing = _WRAPPING_PAIRS.get(text[0])
        if closing is None or text[-1] != closing or not _wraps_whole(text, text[0], closing):
            break
        text = text[1:-1]
    return text


def _remove_symbols(text):
    """6단계: 뜻을 바꾸는 기호(！？… 등)만 남기고 나머지 기호를 지운다."""
    return "".join(
        ch
        for ch in text
        if ch in _MEANINGFUL_SYMBOLS or unicodedata.category(ch)[0] not in ("P", "S")
    )


def analysis_text(original):
    """1~6단계를 적용한 분석 텍스트. 숫자는 그대로라 SudachiPy 입력으로 쓴다."""
    text = original
    for step in (_unify_width, _remove_spaces, _remove_tildes, _remove_wrapping, _remove_symbols):
        text = step(text)
    return text
