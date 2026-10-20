"""분석 API: 숫자 자리표시자, 숫자 뒤 조사 교정, 숫자는 LLM에 보내지 않음."""

import pytest

from tests.analysis.helpers import analyze

pytestmark = pytest.mark.django_db


def test_sentences_differing_only_in_numbers_reuse_analysis(client, fake_llm):
    fake_llm.response = {"translation_ko": "⟨N1⟩명이서 ⟨N2⟩시에 간다."}
    first = analyze(client, "3人で10時に行く。")

    second = analyze(client, "5人で7時に行く。")

    assert first.json()["translation_ko"] == "3명이서 10시에 간다."
    assert second.json()["translation_ko"] == "5명이서 7시에 간다."
    assert len(fake_llm.requests) == 1


def test_particle_after_number_follows_restored_number(client, fake_llm):
    # 1(일)과 2(이)는 같은 캐시를 쓰지만 뒤따르는 조사는 숫자 발음에 따라 다르다.
    fake_llm.response = {"translation_ko": "⟨N1⟩는 맞다"}

    first = analyze(client, "1は正しい")
    second = analyze(client, "2は正しい")

    assert first.json()["translation_ko"] == "1은 맞다"
    assert second.json()["translation_ko"] == "2는 맞다"


@pytest.mark.parametrize(
    ("sentence", "translation", "restored"),
    [
        ("3を選ぶ", "⟨N1⟩를 고른다", "3을 고른다"),  # 삼
        ("4が出た", "⟨N1⟩이 나왔다", "4가 나왔다"),  # 사
        ("6と7", "⟨N1⟩와 ⟨N2⟩", "6과 7"),  # 육
        ("10は多い", "⟨N1⟩는 많다", "10은 많다"),  # 십
        ("20000は多い", "⟨N1⟩는 많다", "20000은 많다"),  # 이만
        ("1で割る", "⟨N1⟩으로 나눈다", "1로 나눈다"),  # 일: ㄹ 받침은 '로'
        ("3で割る", "⟨N1⟩로 나눈다", "3으로 나눈다"),
        ("2で割る", "⟨N1⟩으로는 부족", "2로는 부족"),
        ("3としては", "⟨N1⟩로서는", "3으로서는"),  # (으)로 뒤에 조사가 겹친다
        ("1からは", "⟨N1⟩으로부터는", "1로부터는"),
        ("3でも", "⟨N1⟩로도", "3으로도"),
        ("2は？", "⟨N1⟩은요?", "2는요?"),  # 조사 뒤에 요가 붙는다
        ("1は？", "⟨N1⟩는요?", "1은요?"),
        ("1種類", "⟨N1⟩가지", "1가지"),  # 조사가 아닌 말은 그대로
        ("第2課", "제⟨N1⟩과", "제2과"),  # 원문에서 숫자 뒤가 조사가 아니면 그대로(課)
        ("2課と3課", "⟨N1⟩과와 ⟨N2⟩과", "2과와 3과"),
    ],
)
def test_particle_is_fixed_for_each_number(client, fake_llm, sentence, translation, restored):
    fake_llm.response = {"translation_ko": translation}

    response = analyze(client, sentence)

    assert response.json()["translation_ko"] == restored


def test_numbers_are_not_sent_to_llm(client, fake_llm):
    fake_llm.response = {"translation_ko": "⟨N1⟩명이서 간다."}

    analyze(client, "３人で行く")

    [request] = fake_llm.requests
    assert request["sentence"] == "⟨N1⟩人で行く"
    assert [token["surface"] for token in request["tokens"]] == ["⟨N1⟩", "人", "で", "行く"]


@pytest.mark.parametrize("translation", ["세 명이서 간다.", "⟨N2⟩명이서 간다."])
def test_translation_missing_placeholder_fails_and_is_not_stored(client, fake_llm, translation):
    fake_llm.response = {"translation_ko": translation}

    response = analyze(client, "3人で行く")

    assert response.status_code == 502
    assert response.json() == {"error": "ANALYSIS:FAILED"}
    fake_llm.response = {"translation_ko": "⟨N1⟩명이서 간다."}
    assert analyze(client, "3人で行く").json()["translation_ko"] == "3명이서 간다."
    assert len(fake_llm.requests) == 2
