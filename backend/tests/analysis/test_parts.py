"""긴 패턴 안의 구성 문법 표시(#65)."""

import pytest
from django.test import Client

from analysis import patterns
from analysis.models import GrammarPattern, SentenceAnalysis, SpanMatch
from errors import AnalysisError, BusinessError
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

TESHIMATTA = new_pattern(
    (1, "lemma"),
    (2, "lemma"),
    (3, "lemma"),
    pattern_name="てしまった",
    usage_name="완료 과거",
    explanation_ko="동작을 끝까지 해 버렸다",
    example_ja="見てしまった",
)
SHIMATTA = new_pattern(
    (2, "lemma"),
    (3, "lemma"),
    pattern_name="しまった",
    usage_name="아쉬움",
    explanation_ko="해 버려서 아쉽다",
    example_ja="忘れてしまった",
)
# てしまう와 범위가 같고 しまっ의 활용형까지 고정한 패턴
TESHIMAT = new_pattern(
    (1, "lemma"),
    (2, "form"),
    pattern_name="てしまっ",
    usage_name="완료 연용형",
    explanation_ko="끝까지 해 버린 뒤 다음 말로 잇는다",
    example_ja="見てしまった",
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


@pytest.mark.parametrize(
    ("proposals", "expected"),
    [
        # てしまう(しまっ까지)와 しまった(て 다음부터)는 일부만 겹친다.
        ([TESHIMAU, SHIMATTA], [("완료", []), ("아쉬움", [])]),
        ([TESHIMAU, TESHIMAT], [("완료", []), ("완료 연용형", [])]),
    ],
    ids=["partly-overlapping", "same-range"],
)
def test_partly_overlapping_or_same_range_grammar_are_cards_of_their_own(
    client, fake_llm, proposals, expected
):
    response = analyze_with(client, fake_llm, *proposals)

    assert outline(response.json()["grammar"]) == expected


@pytest.mark.parametrize(
    ("hidden_in", "expected"),
    [
        (None, [("완료 과거", ["연결", "완료"])]),
        ("てしまった", [("완료 과거", [])]),
        # て는 그것을 바로 품은 てしまう 아래에 붙을 자리라 함께 숨는다.
        ("てしまう", [("완료 과거", ["완료"])]),
    ],
)
def test_nested_parts_are_laid_flat_under_the_outermost_card(client, fake_llm, hidden_in, expected):
    analyze_with(client, fake_llm, TESHIMATTA, TESHIMAU, TE)
    GrammarPattern.objects.filter(name=hidden_in).update(show_parts=False)

    response = analyze(client, TABETESHIMATTA)

    assert outline(response.json()["grammar"]) == expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, [("완료", ["연결"]), ("과거", [])]),
        # 재판정이 실패하면 저장하지 않고 저장된 구간만으로 대체 응답을 보낸다.
        (BusinessError(AnalysisError.FAILED, "LLM 재판정 호출 실패"), [("완료", ["연결"])]),
    ],
    ids=["saved", "fallback"],
)
def test_rematch_sends_flat_grammar_first_and_parts_in_the_analysis(
    client, fake_llm, error, expected
):
    analyze_with(client, fake_llm, TESHIMAU, TE)
    # 다른 문장으로 た를 등록하면 패턴 세트 버전이 올라 캐시 문장을 다시 매칭한다(#41).
    analyze_with(
        Client(),
        fake_llm,
        new_pattern(
            (1, "lemma"),
            pattern_name="た",
            usage_name="과거",
            explanation_ko="지난 일을 나타낸다",
            example_ja="食べた",
        ),
        sentence="見た",
    )
    fake_llm.forget_requests()
    # 새 구간 た의 후보 번호는 저장 구간의 후보(て 1, てしまう 2) 다음인 3이다.
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 3)]}
    fake_llm.rematch_error = error

    response = analyze(client, TABETESHIMATTA)

    assert response.types() == ["grammar", "translation", "analysis"]
    first = response.events[0]["grammar"]
    assert outline(first) == [("연결", []), ("완료", [])]
    assert all("parts" not in item for item in first)
    assert outline(response.json()["grammar"]) == expected
