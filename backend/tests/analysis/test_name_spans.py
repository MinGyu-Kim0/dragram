"""이름 구간(#140). 새 문장 첫 LLM 요청이 고유명사 토큰을 함께 판단하고, 서버가 위치를 계산해
저장한다. 확장은 이 값으로 지정한 이름의 기본 보기를 고른다.
"""

import pytest

from analysis.models import SentenceAnalysis, Word
from tests.analysis.helpers import add_word, analyze

pytestmark = pytest.mark.django_db


def name(token_ids, type_="person"):
    return {"token_ids": token_ids, "type": type_}


def test_name_span_is_shown_at_the_original_position(client, fake_llm):
    # 토큰: 0 12 / 1 時 / 2 に / 3 山田 / 4 太郎 / 5 が / 6 来 / 7 た. 키 텍스트는 ⟨N1⟩時に… 라
    # 위치가 원문과 다르다.
    fake_llm.response = {
        "translation_ko": "⟨N1⟩시에 야마다 타로가 왔다",
        "name_spans": [name([3, 4])],
    }

    response = analyze(client, "12時に山田太郎が来た")

    assert response.json()["name_spans"] == [{"start": 4, "end": 8, "type": "person"}]
    assert [(w["dictionary_form"], w["start"], w["end"]) for w in response.json()["words"]] == [
        ("山田", 4, 6),
        ("太郎", 6, 8),
    ]


def test_invalid_name_spans_are_dropped_and_the_rest_is_saved(client, fake_llm):
    # 토큰: 0 春 / 1 が / 2 来 / 3 た
    fake_llm.response = {
        "translation_ko": "하루가 왔다",
        "name_spans": [
            name([4]),
            name([0, 2]),
            name([]),
            name([0], "animal"),
            {"token_ids": "0", "type": "person"},
            name([0]),
        ],
    }

    response = analyze(client, "春が来た")

    assert response.json()["translation_ko"] == "하루가 왔다"
    assert response.json()["name_spans"] == [{"start": 0, "end": 1, "type": "person"}]
    assert SentenceAnalysis.objects.get().name_spans == [{"start": 0, "end": 1, "type": "person"}]


def test_sentence_without_names_has_an_empty_list(client, fake_llm):
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": []}

    response = analyze(client, "春が来た").json()

    assert response["name_spans"] == []
    assert response["words"] == []


def test_row_saved_before_name_spans_is_not_analyzed_again(client, fake_llm):
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": [name([0])]}
    analyze(client, "春が来た")
    SentenceAnalysis.objects.update(name_spans=None)
    fake_llm.forget_requests()

    response = analyze(client, "春が来た")

    assert response.json()["name_spans"] is None
    assert response.json()["words"] == []
    assert fake_llm.all_requests() == []


def test_stale_analysis_replaces_name_spans(client, fake_llm):
    fake_llm.response = {"translation_ko": "하루가 왔다", "name_spans": [name([0])]}
    analyze(client, "春が来た")
    SentenceAnalysis.objects.update(is_stale=True)
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": []}

    response = analyze(client, "春が来た")

    assert response.json()["name_spans"] == []
    assert SentenceAnalysis.objects.get().name_spans == []


def test_answer_without_name_spans_is_saved_as_not_judged(client, fake_llm):
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": "春"}

    response = analyze(client, "春が来た")

    assert response.json()["name_spans"] is None
    assert SentenceAnalysis.objects.get().name_spans is None


def test_designated_names_are_not_sent_to_the_llm(client, fake_llm):
    saved = client.put(
        "/api/names/", {"surface": "春", "reading": "しゅん"}, content_type="application/json"
    )
    assert saved.status_code == 200
    fake_llm.response = {"translation_ko": "봄이 왔다"}

    analyze(client, "春が来た")

    assert "しゅん" not in str(fake_llm.all_requests())


def test_cached_analysis_shows_name_type(client, fake_llm):
    # 토큰: 0 東京 / 1 へ / 2 行っ / 3 た
    fake_llm.response = {"translation_ko": "도쿄에 갔다", "name_spans": [name([0], "place")]}
    analyze(client, "東京へ行った")
    fake_llm.forget_requests()

    response = analyze(client, "東京へ行った")

    assert fake_llm.all_requests() == []
    assert response.json()["name_spans"] == [{"start": 0, "end": 2, "type": "place"}]


def test_name_and_suffix_are_separate_words_in_fresh_and_cached_analysis(client, fake_llm):
    # 예전에 명사로 저장한 경칭도 이 문장의 접미사로 보인다. LLM이 경칭까지 이름 구간에 넣은 경우다.
    san = add_word(1, [], ["さん"], [(["Mr.; Ms."], ["honorific"], None)])
    fake_llm.response = {
        "translation_ko": "니시야마 씨",
        "name_spans": [name([0, 1])],
    }

    response = analyze(client, "西山さん")
    first = response.json()

    assert [(w["dictionary_form"], w["tags"]) for w in first["words"]] == [
        ("西山", ["proper_noun"]),
        ("さん", ["suffix"]),
    ]
    person, suffix = first["words"]
    assert (person["start"], person["end"], person["reading"]) == (0, 2, "にしやま")
    assert person["reading_ko"] == "니시야마"
    assert person["is_name"] is True
    assert person["sense"] is None
    assert suffix["sense"]["tags"] == ["honorific"]
    early = next(event for event in response.events if event["type"] == "grammar")
    assert early["words"][0]["tags"] == ["suffix"]
    # 이름 표기는 응답할 때만 구성하고, 공용 단어·뜻에는 저장하지 않는다.
    assert list(Word.objects.values_list("dictionary_form", flat=True)) == ["さん"]
    assert SentenceAnalysis.objects.get().sense_ids == [san.senses.get().id]

    fake_llm.forget_requests()
    cached = analyze(client, "  西山さん。").json()

    assert fake_llm.all_requests() == []
    assert cached["words"] == [
        {**word, "start": word["start"] + 2, "end": word["end"] + 2} for word in first["words"]
    ]


def test_existing_word_in_a_name_span_is_not_duplicated(client, fake_llm):
    add_word(1, ["春"], ["はる"], [(["spring"], [], None)])
    fake_llm.response = {"translation_ko": "하루가 왔다", "name_spans": [name([0])]}

    response = analyze(client, "春が来た").json()

    [word] = response["words"]
    assert word["dictionary_form"] == "春"
    assert word["sense"]["gloss_en"] == ["spring"]
    assert not word.get("is_name")


def test_place_name_reads_its_administrative_unit_in_korean(client, fake_llm):
    # SudachiPy는 愛知県을 행정 단위까지 한 단어(固有名詞·地名)로 본다(#267).
    fake_llm.response = {
        "translation_ko": "아이치현에 산다",
        "name_spans": [name([0], "place")],
    }

    words = analyze(client, "愛知県に住む").json()["words"]

    place = next(w for w in words if w["dictionary_form"] == "愛知県")
    assert (place["reading"], place["reading_ko"]) == ("あいちけん", "아이치현")


def test_person_name_keeps_plain_reading(client, fake_llm):
    # 지명이 아닌 이름은 지금처럼 가나를 그대로 옮긴다.
    fake_llm.response = {"translation_ko": "니시야마 씨", "name_spans": [name([0, 1])]}

    words = analyze(client, "西山さん").json()["words"]

    person = next(w for w in words if w["dictionary_form"] == "西山")

    assert person["reading_ko"] == "니시야마"
