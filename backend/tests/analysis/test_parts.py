"""긴 패턴 안의 구성 문법 표시(#65)."""

import pytest

from analysis import patterns
from analysis.models import GrammarPattern, SentenceAnalysis, SpanMatch
from tests.analysis.helpers import analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 食べ / 1 て / 2 しまっ / 3 た
TABETESHIMATTA = "食べてしまった"
TE = new_pattern(
    (1, "lemma"),
    pattern_name="て",
    usage_name="연결",
    explanation_ko="앞뒤 동작을 잇는다",
    example_ja="見て笑う",
)
TESHIMAU = new_pattern(
    (1, "lemma"),
    (2, "lemma"),
    pattern_name="てしまう",
    usage_name="완료",
    explanation_ko="동작을 끝까지 해 버린다",
    example_ja="見てしまう",
)


def analyze_with(client, fake_llm, *proposals, sentence=TABETESHIMATTA):
    fake_llm.response = {"translation_ko": "먹어 버렸다", "new_patterns": list(proposals)}
    return analyze(client, sentence)


def test_grammar_inside_a_longer_grammar_is_shown_in_its_parts(client, fake_llm):
    response = analyze_with(client, fake_llm, TESHIMAU, TE)

    assert response.json()["grammar"] == [
        {
            "start": 2,
            "end": 6,
            "state": "decided",
            "name": "완료",
            "explanation_ko": "동작을 끝까지 해 버린다",
            "review_status": "pending",
            "register": "standard",
            "variant_of": None,
            "parts": [
                {
                    "start": 2,
                    "end": 3,
                    "state": "decided",
                    "name": "연결",
                    "explanation_ko": "앞뒤 동작을 잇는다",
                    "review_status": "pending",
                    "register": "standard",
                    "variant_of": None,
                }
            ],
        }
    ]


def outline(grammar):
    """(이름, 구성 문법 이름들) 목록."""
    return [(item["name"], [part["name"] for part in item.get("parts", [])]) for item in grammar]


def test_turning_show_parts_off_hides_the_parts_on_the_next_read_without_reanalysis(
    client, fake_llm
):
    analyze_with(client, fake_llm, TESHIMAU, TE)
    analysis = SentenceAnalysis.objects.get()
    version = patterns.pattern_set_version()

    GrammarPattern.objects.filter(name="てしまう").update(show_parts=False)
    response = analyze(client, TABETESHIMATTA)

    assert outline(response.json()["grammar"]) == [("완료", [])]
    assert "parts" not in response.json()["grammar"][0]
    assert len(fake_llm.requests) == 1
    refreshed = SentenceAnalysis.objects.get()
    assert (refreshed.is_stale, refreshed.generation) == (False, analysis.generation)
    assert patterns.pattern_set_version() == version
    assert SpanMatch.objects.filter(analysis=analysis, pattern__name="て").exists()


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("not_applicable", [("연결", [])]),
        # 미확정 카드는 매칭된 패턴 이름으로 보인다.
        ("unresolved", [("연결", []), ("てしまう", [])]),
    ],
)
def test_grammar_inside_a_not_applicable_or_unresolved_span_is_a_card_of_its_own(
    client, fake_llm, verdict, expected
):
    analyze_with(client, fake_llm, TESHIMAU, TE)
    # 토큰: 0 寝 / 1 て / 2 しまっ / 3 た. 구간 0은 て(후보 1), 구간 1은 てしまう(후보 2)다.
    fake_llm.response = {
        "translation_ko": "자 버렸다",
        "spans": [span_answer(0, "usage", 1), span_answer(1, verdict)],
    }
    # 미확정은 한 번 다시 묻는다(#40). 다시 묻는 구간은 0부터 다시 매긴다.
    fake_llm.rejudge_response = {"translation_ko": "자 버렸다", "spans": [span_answer(0, verdict)]}

    response = analyze(client, "寝てしまった")

    assert outline(response.json()["grammar"]) == expected


def test_grammar_inside_a_rejected_pattern_is_a_card_of_its_own(client, fake_llm):
    analyze_with(client, fake_llm, TESHIMAU, TE)
    # 반려는 조회할 때 보므로, 다시 분석하기 전의 캐시 결과에서도 바깥이 되지 않는다.
    GrammarPattern.objects.filter(name="てしまう").update(status="rejected")

    response = analyze(client, TABETESHIMATTA)

    assert outline(response.json()["grammar"]) == [("연결", [])]
