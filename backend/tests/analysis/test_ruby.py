"""분석 API: 사이드 패널 루비(SudachiPy 읽기)."""

import pytest

from tests.analysis.helpers import analyze

pytestmark = pytest.mark.django_db


def test_ruby_goes_only_over_kanji_without_okurigana(client, fake_llm):
    response = analyze(client, "食べる")

    assert response.json()["ruby"] == [{"start": 0, "end": 1, "reading": "た"}]


def test_kana_only_words_get_no_ruby(client, fake_llm):
    response = analyze(client, "テストとありがとう")

    assert response.json()["ruby"] == []


def test_ruby_positions_follow_original_with_leading_space_and_number(client, fake_llm):
    # 원문 앞의 전각 공백은 분석 텍스트에서 빠지고, 숫자 2에는 한자가 없어 루비가 없다.
    fake_llm.response = {"translation_ko": "⟨N1⟩주 뒤에 먹는다"}

    response = analyze(client, "　2週間後に食べる")

    assert response.json()["ruby"] == [
        {"start": 2, "end": 4, "reading": "しゅうかん"},
        {"start": 4, "end": 5, "reading": "ご"},
        {"start": 6, "end": 7, "reading": "た"},
    ]


def test_ruby_positions_are_utf16(client, fake_llm):
    # 𠮷은 UTF-16에서 두 칸이다. 읽기가 가나가 아닌(사전에 없는) 형태소에는 루비를 달지 않는다.
    response = analyze(client, "𠮷は食べる")

    assert response.json()["ruby"] == [{"start": 3, "end": 4, "reading": "た"}]


def test_kana_inside_word_stays_under_ruby(client, fake_llm):
    # 앞뒤 가나만 떼고 가운데 가나는 함께 덮는다.
    response = analyze(client, "取り扱い")

    assert response.json()["ruby"] == [{"start": 0, "end": 3, "reading": "とりあつか"}]


def test_reused_analysis_computes_ruby_for_this_original(client, fake_llm):
    analyze(client, "食べる")

    response = analyze(client, "  食べる")

    assert len(fake_llm.requests) == 1
    assert response.json()["ruby"] == [{"start": 2, "end": 3, "reading": "た"}]
