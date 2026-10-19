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
_TILDES = set("~〜～")
_DIGITS = re.compile(r"[0-9]+")
_PLACEHOLDER = re.compile(r"⟨N(\d+)⟩")
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
_SIGNS = set("-−－+＋")
_KANJI_NUMERALS = set("〇一二三四五六七八九十百千万")
# 숫자 범위로 보려면 물결표 앞 몇 글자 안에 숫자가 있어야 하는가. 3人〜, 10時〜를 잡는다.
_RANGE_LOOKBEHIND = 3


def _is_digit(ch):
    return len(ch) == 1 and "0" <= ch <= "9"


def _is_number_char(ch):
    """아라비아 숫자 또는 한자 숫자인가."""
    return _is_digit(ch) or ch in _KANJI_NUMERALS


def _is_number_symbol(text, i):
    """숫자 사이의 기호(1.5, 10:30, 10/18, 3〜5)와 숫자 앞 부호(-3, -三)는 숫자의 뜻을 바꾸므로
    지우지 않는다. 지우면 1.5倍가 15倍가 되어 숫자가 틀리고 15倍와 캐시를 함께 쓴다."""
    before = text[i - 1] if i > 0 else ""
    after = text[i + 1] if i + 1 < len(text) else ""
    if text[i] in _SIGNS and _is_number_char(after):
        return True
    return _is_digit(before) and _is_digit(after)


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


def _is_number_range(text, i):
    """물결표가 숫자 범위(3〜5, 3人〜5人, 10時〜12時, 三〜五)를 잇는가.

    바로 뒤가 숫자이고 앞 RANGE_LOOKBEHIND 글자 안에 숫자가 있으면 범위로 본다.
    그보다 멀면 늘인 말투(そうだね〜)로 본다.
    """
    after = text[i + 1] if i + 1 < len(text) else ""
    before = text[max(0, i - _RANGE_LOOKBEHIND) : i]
    return _is_number_char(after) and any(_is_number_char(ch) for ch in before)


def _remove_tildes(text):
    """4단계: 물결표를 지운다. 숫자 범위를 잇는 물결표는 뜻이 있어 남긴다."""
    return "".join(
        ch for i, ch in enumerate(text) if ch not in _TILDES or _is_number_range(text, i)
    )


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
        for i, ch in enumerate(text)
        if ch in _MEANINGFUL_SYMBOLS
        or ch in _TILDES  # 4단계를 지나 남은 물결표는 숫자 범위다.
        or unicodedata.category(ch)[0] not in ("P", "S")
        or _is_number_symbol(text, i)
    )


def analysis_text(original):
    """1~6단계를 적용한 분석 텍스트. 숫자는 그대로라 SudachiPy 입력으로 쓴다."""
    text = original
    for step in (_unify_width, _remove_spaces, _remove_tildes, _remove_wrapping, _remove_symbols):
        text = step(text)
    return text


def key_pieces(analysis):
    """7단계: 아라비아 숫자 연속열에 앞에서부터 ⟨N1⟩, ⟨N2⟩…를 매긴다. 한자 숫자는 그대로다.

    분석 텍스트 글자마다 키 텍스트 조각을 돌려준다. 숫자열의 첫 글자는 자리표시자, 나머지
    숫자는 빈 문자열이다. 이어 붙이면 키 텍스트가 되고, 분석 텍스트 위치로 잘라 붙이면 그
    구간의 키 텍스트가 된다. 숫자는 번역에 되돌려 넣을 수 있게 따로 돌려준다.
    """
    pieces = list(analysis)
    numbers = []
    for match in _DIGITS.finditer(analysis):
        numbers.append(match.group())
        pieces[match.start()] = f"⟨N{len(numbers)}⟩"
        for i in range(match.start() + 1, match.end()):
            pieces[i] = ""
    return pieces, numbers


def has_all_placeholders(text, numbers):
    """키 텍스트의 자리표시자가 빠짐없이 있고, 없는 번호는 쓰지 않았는가."""
    found = {int(n) for n in _PLACEHOLDER.findall(text)}
    return found == set(range(1, len(numbers) + 1))


def restore_numbers(text, numbers):
    """자리표시자에 원문 숫자를 같은 순서로 넣는다."""
    return _PLACEHOLDER.sub(lambda m: numbers[int(m.group(1)) - 1], text)
