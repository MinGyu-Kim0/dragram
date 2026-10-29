"""문장 정규화. 규칙과 순서는 docs/requirements.md "정규화 규칙" 표를 따른다.

1단계(루비 제거)는 확장이 원문을 보낼 때 이미 했다. 서버는 2단계부터 한다.
규칙을 바꾸면 NORMALIZE_VERSION을 올린다.
"""

import re
import unicodedata

from analysis.particles import particle_for

NORMALIZE_VERSION = 1

_HALFWIDTH_KANA = re.compile(r"[\uFF61-\uFF9F]+")
_SPACE = re.compile(r"\s+")
_LATIN = re.compile(r"[A-Za-z0-9]")
_TILDES = set("~〜～")
_DIGITS = re.compile(r"[0-9]+")
_PLACEHOLDER = re.compile(r"⟨N(\d+)⟩")
# 자리표시자와, 바로 뒤에 붙은 조사. 조사 뒤에 한글이 이어지면(⟨N1⟩가지) 조사가 아니라고 본다.
# (으)로는 뒤에 붙는 조사(로서, 로부터)와 그 뒤의 보조사(로서는, 로부터도)까지 허용한다.
# 조사 끝에 붙는 높임의 요(는요?, 로요)도 허용한다.
_PLACEHOLDER_WITH_PARTICLE = re.compile(
    r"⟨N(\d+)⟩(?:(은|는|이|가|을|를|과|와)(?=요?(?![가-힣]))"
    r"|(으로|로)(?=(?:서|써|부터)?(?:는|도|만|의)?요?(?![가-힣])))?"
)
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
_KANJI_NUMERALS = set("〇零一二三四五六七八九十百千万億兆")
# 숫자 바로 뒤의 단위 기호와 바로 앞의 통화 기호. 지우면 50%가 50과 같아진다.
_UNITS = set("%％‰°℃")
_CURRENCIES = set("¥￥$＄€£₩")
# 숫자 범위로 보려면 물결표 앞 몇 글자 안에 숫자가 있어야 하는가. 3人〜, 10時〜를 잡는다.
_RANGE_LOOKBEHIND = 3


def _is_digit(ch):
    return len(ch) == 1 and "0" <= ch <= "9"


def _is_number_char(ch):
    """아라비아 숫자 또는 한자 숫자인가."""
    return _is_digit(ch) or ch in _KANJI_NUMERALS


def _is_number_symbol(text, i):
    """숫자 사이의 기호(1.5, 10:30, 10/18, 3〜5), 숫자 앞 부호(-3, -三), 숫자에 붙은 단위·통화
    기호(50%, ¥500)는 숫자의 뜻을 바꾸므로
    지우지 않는다. 지우면 1.5倍가 15倍가 되어 숫자가 틀리고 15倍와 캐시를 함께 쓴다."""
    before = text[i - 1] if i > 0 else ""
    after = text[i + 1] if i + 1 < len(text) else ""
    # 숫자는 아라비아 숫자와 한자 숫자를 함께 본다(五％, ￥五百, 三/五).
    if text[i] in _SIGNS or text[i] in _CURRENCIES:
        return _is_number_char(after)
    if text[i] in _UNITS:
        return _is_number_char(before)
    return _is_number_char(before) and _is_number_char(after)


# 정규화는 글자마다 원문 위치를 들고 다닌다. 한 글자는 (글자, 원문 시작, 원문 끝)이고 위치는
# 원문 코드포인트 기준 [시작, 끝)이다. 여러 원문 글자가 한 글자로 합쳐지면(ｶﾞ → ガ) 그 범위
# 전체를 갖는다.


def _text(chars):
    return "".join(ch for ch, _, _ in chars)


def _keep(chars, keeps):
    """keeps(text, i)가 참인 글자만 남긴다."""
    text = _text(chars)
    return [char for i, char in enumerate(chars) if keeps(text, i)]


def _unify_width(chars):
    """2단계: 전각 영숫자는 반각으로, 반각 가나는 전각으로. NFKC 전체는 적용하지 않는다.

    먼저 NFC(정준 결합)로 결합 문자를 합친다(か + 결합 탁점 → が). NFC는 호환 분해를 하지
    않아 x² 같은 문자는 그대로다. 반각 가나는 뒤따르는 반각 탁점·반탁점과 합쳐야 해서
    (ｶﾞ → ガ) 그 범위에만 NFKC를 쓴다.
    """
    # 결합 문자, NFC로 앞 글자와 합쳐지는 글자(결합 등급 0인 한글 자모 등), 반각 탁점·반탁점은
    # 앞 글자와 한 묶음으로 바꾼다.
    groups = []
    for ch, start, end in chars:
        if groups and (
            unicodedata.combining(ch) or ch in "\uff9e\uff9f" or _composes(groups[-1][0], ch)
        ):
            text, group_start, _ = groups[-1]
            groups[-1] = (text + ch, group_start, end)
        else:
            groups.append((ch, start, end))

    result = []
    for text, start, end in groups:
        text = "".join(_to_halfwidth_alnum(ch) for ch in unicodedata.normalize("NFC", text))
        text = _HALFWIDTH_KANA.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)
        result.extend((ch, start, end) for ch in text)
    return result


def _composes(text, ch):
    """ch를 붙이면 NFC가 앞 묶음과 합쳐 글자 수가 늘지 않는가(ᄒ + ᅡ → 하)."""
    return len(unicodedata.normalize("NFC", text + ch)) <= len(unicodedata.normalize("NFC", text))


def _to_halfwidth_alnum(ch):
    code = ord(ch)
    is_fullwidth_alnum = (
        0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A
    )
    return chr(code - 0xFEE0) if is_fullwidth_alnum else ch


def _remove_spaces(chars):
    """3단계: 일본어 문자 사이 공백은 지우고, 영어 단어 사이는 공백 하나만 남긴다.

    제로 폭 공백(U+200B)·BOM 같은 보이지 않는 형식 문자(Cf)도 지운다. 웹 문장에 섞여 들어와
    화면에서는 같은 문장의 해시를 가르기 때문이다.
    """
    chars = [char for char in chars if unicodedata.category(char[0]) != "Cf"]
    result = []
    i = 0
    while i < len(chars):
        if not chars[i][0].isspace():
            result.append(chars[i])
            i += 1
            continue
        run_start = i
        while i < len(chars) and chars[i][0].isspace():
            i += 1
        before = result[-1][0] if result else ""
        after = chars[i][0] if i < len(chars) else ""
        if _LATIN.fullmatch(before) and _LATIN.fullmatch(after):
            _, start, end = chars[run_start]
            result.append((" ", start, end))
    return result


def _is_number_range(text, i):
    """물결표가 숫자 범위(3〜5, 3人〜5人, 10時〜12時, 三〜五, -5〜-3)를 잇는가.

    바로 뒤가 숫자이고 앞 RANGE_LOOKBEHIND 글자 안에 숫자가 있으면 범위로 본다.
    끝점 앞의 부호·통화 기호(-5〜-3, ¥300〜¥500)는 건너뛰고 본다.
    그보다 멀면 늘인 말투(そうだね〜)로 본다.
    """
    j = i + 1
    while j < len(text) and (text[j] in _SIGNS or text[j] in _CURRENCIES):
        j += 1
    after = text[j] if j < len(text) else ""
    before = text[max(0, i - _RANGE_LOOKBEHIND) : i]
    return _is_number_char(after) and any(_is_number_char(ch) for ch in before)


def _remove_tildes(chars):
    """4단계: 물결표를 지운다. 숫자 범위를 잇는 물결표는 뜻이 있어 남긴다."""
    return _keep(chars, lambda text, i: text[i] not in _TILDES or _is_number_range(text, i))


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


def _remove_wrapping(chars):
    """5단계: 문장 전체를 감싼 바깥 괄호·따옴표만 지운다."""
    while len(chars) >= 2:
        text = _text(chars)
        closing = _WRAPPING_PAIRS.get(text[0])
        if closing is None or text[-1] != closing or not _wraps_whole(text, text[0], closing):
            break
        chars = chars[1:-1]
    return chars


def _is_kept_symbol(text, i):
    ch = text[i]
    return (
        ch in _MEANINGFUL_SYMBOLS
        or ch in _TILDES  # 4단계를 지나 남은 물결표는 숫자 범위다.
        or unicodedata.category(ch)[0] not in ("P", "S")
        or _is_number_symbol(text, i)
    )


def _remove_symbols(chars):
    """6단계: 뜻을 바꾸는 기호(！？… 등)만 남기고 나머지 기호를 지운다."""
    return _keep(chars, _is_kept_symbol)


def analysis_text(original):
    """1~6단계를 적용한 분석 텍스트와, 그 글자마다의 원문 위치 [(시작, 끝)].

    분석 텍스트는 숫자가 그대로라 SudachiPy 입력으로 쓴다. 위치는 원문 코드포인트 기준이다.
    """
    chars = [(ch, i, i + 1) for i, ch in enumerate(original)]
    for step in (_unify_width, _remove_spaces, _remove_tildes, _remove_wrapping, _remove_symbols):
        chars = step(chars)
    return _text(chars), [(start, end) for _, start, end in chars]


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


def has_only_known_placeholders(text, numbers):
    """키 텍스트에 있는 번호의 자리표시자만 썼는가(하나도 없어도 된다)."""
    found = {int(n) for n in _PLACEHOLDER.findall(text)}
    return found <= set(range(1, len(numbers) + 1))


def number_ends(analysis):
    """분석 텍스트에서 숫자열(⟨N1⟩, ⟨N2⟩ … 순서)이 끝나는 위치."""
    return [match.end() for match in _DIGITS.finditer(analysis)]


def restore_numbers(text, numbers, particle_numbers=frozenset()):
    """자리표시자에 원문 숫자를 같은 순서로 넣는다.

    particle_numbers에 든 자리표시자(원문에서 바로 뒤가 조사인 숫자)는 번역에서 바로 뒤에
    붙은 조사를 그 숫자 발음에 맞춘다. 원문에서 조사가 아닌 말이 이어지면(第2課) 번역의
    같은 글자도 조사가 아니므로(제2과) 건드리지 않는다.
    """

    def replace(match):
        index = int(match.group(1))
        number = numbers[index - 1]
        particle = match.group(2) or match.group(3)
        if not particle:
            return number
        if index not in particle_numbers:
            return number + particle
        return number + particle_for(number, particle)

    return _PLACEHOLDER_WITH_PARTICLE.sub(replace, text)
