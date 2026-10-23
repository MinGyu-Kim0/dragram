"""판별 규칙(usage_rule): 구간 앞뒤 형태소 조건으로 후보 용법 하나를 고르는 관리자 지식(#55).

조건은 구간 바깥 토큰에 거는 조건 목록이고 모두 맞아야 한다(AND). 각 조건의 position은 구간
기준 상대 위치(-2, -1은 앞, 1, 2는 뒤)이고, 나머지 칸은 형태소 값과 같아야 한다. 비운 칸은
아무거나다. lemma는 매칭과 같은 값(탁음화 보정 뒤)으로 비교한다.
"""

POSITIONS = (-2, -1, 1, 2)
# 조건 칸 → Morpheme 속성
_FIELDS = {
    "lemma": "lemma",
    "pos1": "pos",
    "pos2": "pos2",
    "pos3": "pos3",
    "conjugation_form": "conjugation_form",
}


def condition_problem(condition):
    """조건 형식이 틀린 이유(관리자에게 보임). 맞으면 None."""
    if not isinstance(condition, list) or not condition:
        return "조건은 하나 이상인 목록이어야 합니다"
    for c in condition:
        if not isinstance(c, dict):
            return "조건마다 {position, 칸들} 객체여야 합니다"
        position = c.get("position")
        if type(position) is not int or position not in POSITIONS:
            return "position은 -2, -1, 1, 2 중 하나여야 합니다"
        unknown = set(c) - {"position", *_FIELDS}
        if unknown:
            return f"모르는 칸입니다: {', '.join(sorted(unknown))}"
        if any(not isinstance(c[key], str) for key in _FIELDS if c.get(key) is not None):
            return "칸 값은 글자여야 합니다"
    return None


def condition_matches(condition, morphs, start_token, end_token):
    """형태소열의 구간(start_token~end_token) 앞뒤가 조건에 모두 맞는가."""
    for c in condition:
        position = c["position"]
        index = start_token + position if position < 0 else end_token + position
        if not 0 <= index < len(morphs):
            return False
        morph = morphs[index]
        if any(c.get(key) and c[key] != getattr(morph, attr) for key, attr in _FIELDS.items()):
            return False
    return True
