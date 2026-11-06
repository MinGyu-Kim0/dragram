"""구조화 출력 스트림의 조각 파서."""

import json

from errors import AnalysisError, BusinessError


class SectionParser:
    """구조화 출력 JSON 조각을 이어 받아, 맨 위 객체의 칸이 닫히는 대로 (이름, 값)을 꺼낸다.

    구조화 출력은 스키마의 속성 순서대로 쓰므로 번역이 맨 앞, 판정(spans)이 그다음에 닫힌다(#204).
    받은 글자는 한 번씩만 훑는다. 문자열 안의 괄호·따옴표(\" 등)는 칸을 닫지 않는다.
    """

    def __init__(self):
        self._text = ""
        self._scanned = 0
        self._depth = 0
        self._in_string = False
        self._escaped = False
        self._key_start = None
        self._key = None
        # 지금 칸 값의 시작 위치(맨 위에서 ':' 뒤). 값을 꺼냈거나 아직 이름이면 None
        self._value_start = None

    def feed(self, delta):
        """조각을 더하고, 이번에 닫힌 칸들의 [(이름, 값)]을 돌려준다."""
        self._text += delta
        found = []
        for i in range(self._scanned, len(self._text)):
            char = self._text[i]
            if self._in_string:
                if self._escaped:
                    self._escaped = False
                elif char == "\\":
                    self._escaped = True
                elif char == '"':
                    self._in_string = False
                    if self._depth == 1:
                        found += self._close_string(i)
            elif char == '"':
                self._in_string = True
                if self._depth == 1 and self._value_start is None:
                    self._key_start = i
            elif char in "{[":
                self._depth += 1
            elif char in "}]":
                self._depth -= 1
                # 배열·객체 값이 닫혔거나(맨 위로 돌아옴), 맨 위 객체가 닫히며 숫자 등이 끝났다.
                if self._depth in (0, 1):
                    found += self._close(i + 1 if self._depth == 1 else i)
            elif char == ":" and self._depth == 1:
                self._value_start = i + 1
            elif char == "," and self._depth == 1:
                found += self._close(i)
        self._scanned = len(self._text)
        return found

    def partial(self, key):
        """맨 위 칸 key의 값이 아직 닫히지 않은 문자열이면 지금까지 받은 앞부분, 아니면 None.

        조각 끝에서 잘린 이스케이프(\\, \\u30 등)와 짝을 기다리는 서로게이트는 빼고 돌려준다.
        """
        if not (self._in_string and self._depth == 1) or self._value_start is None:
            return None
        if self._key != key:
            return None
        raw = self._text[self._value_start :].lstrip()[1:]
        # 잘린 이스케이프는 길어야 \uXXX(5글자)다.
        for end in range(len(raw), max(len(raw) - 6, -1), -1):
            try:
                text = json.loads(f'"{raw[:end]}"', strict=False)
            except json.JSONDecodeError:
                continue
            if text and "\ud800" <= text[-1] <= "\udbff":
                text = text[:-1]
            return text
        # 앞쪽에 JSON이 허용하지 않는 이스케이프가 있다. 칸이 닫힐 때 실패한다.
        return None

    def _close_string(self, end):
        """맨 위에서 닫힌 문자열이 칸 이름이면 기억하고, 값이면 그 칸을 꺼낸다."""
        if self._value_start is None:
            self._key = self._loads(self._text[self._key_start : end + 1])
            return []
        return self._close(end + 1)

    def _close(self, end):
        if self._value_start is None:
            return []
        value = self._loads(self._text[self._value_start : end])
        self._value_start = None
        return [(self._key, value)]

    @staticmethod
    def _loads(text):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # 이스케이프는 훑을 때 검사하지 않아, JSON이 허용하지 않는 것(\x 등)이 여기서 걸린다.
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 칸이 JSON이 아님") from e

    def result(self):
        """다 받은 응답. JSON이 아니면(거절, 끊긴 응답 등) ANALYSIS:FAILED다."""
        try:
            return json.loads(self._text)
        except json.JSONDecodeError as e:
            raise BusinessError(AnalysisError.FAILED, "LLM 응답이 JSON이 아님") from e
