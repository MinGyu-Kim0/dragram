"""문법 카드의 패턴 이름은 원문 형태와 별도로, 기존 응답에 함께 싣는다(#228)."""

import pytest

from tests.analysis.helpers import analyze, span_answer
from tests.analysis.test_single_usage import closed_teiru, register_teiru

pytestmark = pytest.mark.django_db


def test_inflected_pattern_name_is_sent_early_and_reused_without_extra_calls(client, fake_llm):
    closed_teiru(client, fake_llm)
    fake_llm.requests.clear()
    fake_llm.response = {"translation_ko": "먹고 있습니다"}

    response = analyze(client, "食べています")

    assert response.types() == ["grammar", "translation", "analysis"]
    [early] = response.events[0]["grammar"]
    assert early["pattern_name"] == "ている"
    assert (early["start"], early["end"]) == (2, 4)
    assert early["name"] == "진행"
    assert early["explanation_ko"] == "동작이 이어지고 있음을 나타낸다"
    assert response.json()["grammar"] == [early]
    assert len(fake_llm.requests) == 1

    cached = analyze(client, "食べています")

    assert cached.types() == ["translation", "analysis"]
    assert cached.json()["grammar"] == [early]
    assert len(fake_llm.requests) == 1


@pytest.mark.parametrize("verdict", ["usage", "unresolved"])
def test_checking_and_judged_or_unresolved_items_keep_the_pattern_name(client, fake_llm, verdict):
    register_teiru(client, fake_llm)
    fake_llm.response = {
        "translation_ko": "먹고 있습니다",
        "spans": [span_answer(0, verdict, 1 if verdict == "usage" else None)],
    }
    fake_llm.rejudge_response = fake_llm.response

    response = analyze(client, "食べています")

    [checking] = response.events[0]["checking"]
    assert checking["pattern_name"] == "ている"
    assert checking["usage"]["pattern_name"] == "ている"
    [final] = response.json()["grammar"]
    assert final["pattern_name"] == "ている"
    assert (final["start"], final["end"]) == (2, 4)
