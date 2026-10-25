"""이름 구간(#140). 새 문장 첫 LLM 요청이 고유명사 토큰을 함께 판단하고, 서버가 위치를 계산해
저장한다. 확장은 이 값으로 지정한 이름의 기본 보기를 고른다.
"""

import pytest

from analysis.models import SentenceAnalysis
from tests.analysis.helpers import analyze

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

    assert response.json()["name_spans"] == [{"start": 4, "end": 8}]


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
    assert response.json()["name_spans"] == [{"start": 0, "end": 1}]
    assert SentenceAnalysis.objects.get().name_spans == [{"start": 0, "end": 1, "type": "person"}]


def test_sentence_without_names_has_an_empty_list(client, fake_llm):
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": []}

    assert analyze(client, "春が来た").json()["name_spans"] == []


def test_row_saved_before_name_spans_is_not_analyzed_again(client, fake_llm):
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": [name([0])]}
    analyze(client, "春が来た")
    SentenceAnalysis.objects.update(name_spans=None)
    fake_llm.forget_requests()

    response = analyze(client, "春が来た")

    assert response.json()["name_spans"] is None
    assert fake_llm.all_requests() == []


def test_stale_analysis_replaces_name_spans(client, fake_llm):
    fake_llm.response = {"translation_ko": "하루가 왔다", "name_spans": [name([0])]}
    analyze(client, "春が来た")
    SentenceAnalysis.objects.update(is_stale=True)
    fake_llm.response = {"translation_ko": "봄이 왔다", "name_spans": []}

    response = analyze(client, "春が来た")

    assert response.json()["name_spans"] == []
    assert SentenceAnalysis.objects.get().name_spans == []
