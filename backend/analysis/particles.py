"""번역에 되돌린 숫자 뒤의 한국어 조사를 숫자 발음에 맞춘다.

숫자만 다른 문장(1は / 2は)은 같은 번역을 함께 쓰므로, LLM이 고른 조사(⟨N1⟩는)가 숫자에
따라 틀린다(1는). 숫자를 한자어로 읽은 끝소리(일, 이, 십, 만 …)로 조사를 다시 고른다.
고유어로 읽는 경우(두 개 등)는 조수사가 붙어 조사가 숫자에 바로 붙지 않으므로 다루지 않는다.
"""

# 한 자리 숫자를 한자어로 읽은 끝소리. None은 받침 없음.
_DIGIT_FINAL = {
    "0": "ㅇ",  # 영
    "1": "ㄹ",  # 일
    "2": None,  # 이
    "3": "ㅁ",  # 삼
    "4": None,  # 사
    "5": None,  # 오
    "6": "ㄱ",  # 육
    "7": "ㄹ",  # 칠
    "8": "ㄹ",  # 팔
    "9": None,  # 구
}
# 끝자리가 0일 때 읽기가 끝나는 단위. 십·백·천은 네 자리 묶음 안, 만·억·조·경은 묶음 단위다.
_PLACE_FINAL = {1: "ㅂ", 2: "ㄱ", 3: "ㄴ"}  # 십, 백, 천
_GROUP_FINAL = {1: "ㄴ", 2: "ㄱ", 3: None, 4: "ㅇ"}  # 만, 억, 조, 경

# (받침 있을 때, 받침 없을 때)
_PAIRS = [("은", "는"), ("이", "가"), ("을", "를"), ("과", "와")]
_PARTICLES = {particle: pair for pair in _PAIRS for particle in pair}


def _final_consonant(number):
    """아라비아 숫자열을 한자어로 읽었을 때 마지막 음절의 받침."""
    digits = number.lstrip("0")
    if not digits:
        return _DIGIT_FINAL["0"]
    zeros = len(digits) - len(digits.rstrip("0"))
    if zeros == 0:
        return _DIGIT_FINAL[digits[-1]]
    if zeros < 4:
        return _PLACE_FINAL[zeros]
    return _GROUP_FINAL.get(zeros // 4)


def particle_for(number, particle):
    """숫자 뒤에 붙을 조사를 숫자 발음에 맞춰 고른다. 다루지 않는 조사는 그대로 둔다."""
    final = _final_consonant(number)
    if particle in ("으로", "로"):
        # ㄹ 받침 뒤에는 '로'를 쓴다(일로, 칠로).
        return "으로" if final not in (None, "ㄹ") else "로"
    with_final, without_final = _PARTICLES[particle]
    return with_final if final else without_final
