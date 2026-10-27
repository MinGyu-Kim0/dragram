import pytest

from analysis.korean_reading import korean_reading


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        ("にしやま", "니시야마"),
        ("ニシヤマ", "니시야마"),
        ("ﾆｼﾔﾏ", "니시야마"),
        ("やまだ", "야마다"),
        ("たなか", "다나카"),
        ("すずき", "스즈키"),
        ("さとう", "사토"),
        ("とうきょう", "도쿄"),
        ("たろう", "다로"),
        ("きくち", "기쿠치"),
        ("ちば", "지바"),
        ("きょうと", "교토"),
        ("しんじゅく", "신주쿠"),
        ("じゅん", "준"),
        ("はっとり", "핫토리"),
        ("いっぺい", "잇페이"),
        ("けいこ", "게이코"),
        ("おおの", "오노"),
        ("ゆうき", "유키"),
        ("ジョージ", "조지"),
        ("しゅうへい", "슈헤이"),
        ("りょう", "료"),
        ("", None),
        ("西山", None),
        ("Nishiyama", None),
        ("にしやま123", None),
        ("ー", None),
        ("っ", None),
        ("ゃ", None),
    ],
)
def test_kana_name_reading(reading, expected):
    assert korean_reading(reading) == expected
