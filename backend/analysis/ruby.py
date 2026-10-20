"""사이드 패널 루비. SudachiPy 추정 읽기로 한자 위에 올릴 읽기 조각을 만든다.

design-decisions 28절 14.

요청마다 계산하고 저장하지 않는다. 위치는 분석 텍스트 기준 [start, end)이다.
"""

import re

# 한자(CJK 통합 한자와 확장, 호환 한자)와 한자 숫자 〇(U+3007, 통합 한자 블록 밖).
# 々·〆·ヶ는 한자와 함께 있을 때만 루비 안에 들어간다.
_KANJI = re.compile("[\u3007\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f]")
# 읽기로 받는 글자: 히라가나와 장음
_HIRAGANA_READING = re.compile("[\u3041-\u3096\u309d\u309e\u30fc]+")


def _to_hiragana(text):
    """가타카나(ァ-ヶ 범위)를 히라가나로 바꾼다. 나머지 글자는 그대로다."""
    return "".join(chr(ord(ch) - 0x60) if "\u30a1" <= ch <= "\u30f6" else ch for ch in text)


def ruby_pieces(text, morphs):
    """한자가 있는 형태소마다 (시작, 끝, 히라가나 읽기)를 만든다.

    표기와 읽기의 앞뒤에서 같은 가나를 떼어(오쿠리가나) 한자 부분 위에만 읽기를 단다
    (食べる → 食 / た). 가운데 가나는 떼지 않고 함께 덮는다(取り扱い → 取り扱 / とりあつか).
    읽기가 가나가 아니면(사전에 없는 말은 표기 그대로일 수 있다) 루비를 달지 않는다.
    """
    pieces = []
    for m in morphs:
        surface = text[m.begin : m.end]
        reading = _to_hiragana(m.reading)
        if not _KANJI.search(surface) or not _HIRAGANA_READING.fullmatch(reading):
            continue
        kana = _to_hiragana(surface)
        start, end = 0, len(surface)
        head, tail = 0, len(reading)
        # 앞뒤에서 표기와 읽기가 같은 가나를 뗀다. 읽기는 히라가나뿐이라 한자에서 멈춘다.
        while start < end and head < tail and kana[start] == reading[head]:
            start += 1
            head += 1
        while start < end and head < tail and kana[end - 1] == reading[tail - 1]:
            end -= 1
            tail -= 1
        if head == tail:
            # 한자 부분에 남는 읽기가 없으면 나눌 수 없다. 단어 전체 위에 단다.
            start, end, head, tail = 0, len(surface), 0, len(reading)
        pieces.append((m.begin + start, m.begin + end, reading[head:tail]))
    return pieces
