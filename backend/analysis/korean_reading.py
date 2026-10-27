"""이름의 가나 읽기를 한글로 옮긴다. 뜻 생성이나 추가 LLM 호출은 하지 않는다.

기준: 국립국어원 외래어 표기법의 일본어 대조표·표기 세칙.
https://www.korean.go.kr/kornorms/m/m_regltn.do?regltn_code=0003
"""

import unicodedata

from analysis.jmdict import to_hiragana

_KANA = {
    kana: hangul
    for kana_row, hangul_row in (
        ("あ い う え お", "아 이 우 에 오"),
        ("か き く け こ", "카 키 쿠 케 코"),
        ("さ し す せ そ", "사 시 스 세 소"),
        ("た ち つ て と", "타 치 쓰 테 토"),
        ("な に ぬ ね の", "나 니 누 네 노"),
        ("は ひ ふ へ ほ", "하 히 후 헤 호"),
        ("ま み む め も", "마 미 무 메 모"),
        ("や ゆ よ", "야 유 요"),
        ("ら り る れ ろ", "라 리 루 레 로"),
        ("わ ゐ ゑ を", "와 이 에 오"),
        ("が ぎ ぐ げ ご", "가 기 구 게 고"),
        ("ざ じ ず ぜ ぞ", "자 지 즈 제 조"),
        ("だ ぢ づ で ど", "다 지 즈 데 도"),
        ("ば び ぶ べ ぼ", "바 비 부 베 보"),
        ("ぱ ぴ ぷ ぺ ぽ", "파 피 푸 페 포"),
        ("きゃ きゅ きょ", "캬 큐 쿄"),
        ("ぎゃ ぎゅ ぎょ", "갸 규 교"),
        ("しゃ しゅ しょ", "샤 슈 쇼"),
        ("じゃ じゅ じょ", "자 주 조"),
        ("ちゃ ちゅ ちょ", "차 추 초"),
        ("にゃ にゅ にょ", "냐 뉴 뇨"),
        ("ひゃ ひゅ ひょ", "햐 휴 효"),
        ("びゃ びゅ びょ", "뱌 뷰 뵤"),
        ("ぴゃ ぴゅ ぴょ", "퍄 퓨 표"),
        ("みゃ みゅ みょ", "먀 뮤 묘"),
        ("りゃ りゅ りょ", "랴 류 료"),
    )
    for kana, hangul in zip(kana_row.split(), hangul_row.split(), strict=True)
}
_INITIAL = dict(
    zip(
        "か き く け こ た ち て と きゃ きゅ きょ ちゃ ちゅ ちょ".split(),
        "가 기 구 게 고 다 지 데 도 갸 규 교 자 주 조".split(),
        strict=True,
    )
)
_VOWELS = {
    **dict.fromkeys("あかがさざただなはばぱまやゃらわ", "あ"),
    **dict.fromkeys("いきぎしじちぢにひびぴみりゐ", "い"),
    **dict.fromkeys("うくぐすずつづぬふぶぷむゆゅる", "う"),
    **dict.fromkeys("えけげせぜてでねへべぺめれゑ", "え"),
    **dict.fromkeys("おこごそぞとどのほぼぽもよょろを", "お"),
}


def korean_reading(reading):
    """읽을 수 없는 글자가 섞였으면 부분 음차를 만들지 않고 None을 돌려준다."""
    reading = to_hiragana(unicodedata.normalize("NFKC", reading))
    result = []
    previous_vowel = None
    at = 0
    while at < len(reading):
        char = reading[at]
        if char in "んっ":
            if not result or (ord(result[-1]) - ord("가")) % 28:
                return None
            result[-1] = chr(ord(result[-1]) + (4 if char == "ん" else 19))
            previous_vowel = None
            at += 1
            continue
        if char == "ー":
            if previous_vowel is None:
                return None
            at += 1
            continue
        # shortcut: 가나만으로 합성 이름의 모음 경계·관용 표기를 알 수 없다. 표기별 교정이
        # 필요해지면 개인 읽기 교정을 확장한다. えい는 보존하고, 장음은 겹쳐 적지 않는다.
        if char == previous_vowel or (previous_vowel == "お" and char == "う"):
            at += 1
            continue
        kana = reading[at : at + 2]
        if kana not in _KANA:
            kana = char
        hangul = (_INITIAL if not result else {}).get(kana, _KANA.get(kana))
        if hangul is None:
            return None
        result.append(hangul)
        previous_vowel = _VOWELS[kana[-1]]
        at += len(kana)
    return "".join(result) or None
