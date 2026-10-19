"""분석 텍스트와 키 텍스트 사이의 위치 변환.

키 텍스트는 분석 텍스트 글자마다 조각을 이어 만든다(normalize.key_pieces). 숫자열의 첫 글자는
자리표시자(⟨N1⟩), 나머지 숫자는 빈 조각이다. 구간은 모두 반열린 구간 [start, end)이다.
"""

from bisect import bisect_left, bisect_right
from itertools import accumulate


def key_offsets(pieces):
    """분석 텍스트 위치 i가 키 텍스트에서 시작하는 위치. 길이는 분석 텍스트 길이 + 1이다."""
    return [0, *accumulate(len(piece) for piece in pieces)]


def to_key(offsets, start, end):
    """분석 텍스트 구간을 키 텍스트 구간으로 바꾼다."""
    return offsets[start], offsets[end]


def to_analysis(offsets, start, end):
    """키 텍스트 구간을 분석 텍스트 구간으로 바꾼다.

    자리표시자를 덮는 구간은 숫자열 전체를 덮는다(⟨N1⟩ → 12). 빈 조각이 여러 위치에
    같은 키 위치를 주므로, 시작은 그 위치에서 시작하는 첫 글자, 끝은 그 위치에서 끝나는
    마지막 글자로 잡는다.
    """
    return bisect_left(offsets, start), bisect_right(offsets, end) - 1


def utf16_offsets(original):
    """원문 코드포인트 위치 i가 UTF-16(브라우저 문자열)에서 시작하는 위치. 길이는 원문 + 1."""
    return [0, *accumulate(2 if ord(ch) > 0xFFFF else 1 for ch in original)]


def to_original(origins, utf16, start, end):
    """분석 텍스트 구간을 원문 UTF-16 구간으로 바꾼다.

    origins는 분석 텍스트 글자마다의 원문 코드포인트 범위다. 구간은 첫 글자의 원문 시작부터
    마지막 글자의 원문 끝까지다(합쳐진 글자는 원문의 여러 글자를 덮는다).
    """
    return utf16[origins[start][0]], utf16[origins[end - 1][1]]
