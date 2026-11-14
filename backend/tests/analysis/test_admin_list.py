"""검수 목록: 상태 배지와 패턴 목록의 '검수할 것 있음' 필터(#452)."""

import html

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from analysis.models import GrammarPattern, GrammarUsage, ReviewStatus, UsageRule

pytestmark = pytest.mark.django_db

PATTERNS = "/admin/analysis/grammarpattern/"
TO_REVIEW = f"{PATTERNS}?to_review=yes"

APPROVED = ReviewStatus.APPROVED
PENDING = ReviewStatus.PENDING
REJECTED = ReviewStatus.REJECTED


def pattern(name, **fields):
    defaults = {"is_active": True, "status": APPROVED}
    # morpheme_key는 유일해야 해서 이름에서 만든다.
    key = name.encode().hex().ljust(64, "0")[:64]
    return GrammarPattern.objects.create(name=name, morpheme_key=key, **defaults | fields)


def usage(of, name="용법", **fields):
    defaults = {"explanation_ko": "설명", "status": APPROVED, "origin": "llm"}
    return GrammarUsage.objects.create(pattern=of, name=name, **defaults | fields)


def rule(of, status):
    return UsageRule.objects.create(
        pattern=of,
        usage=usage(of, f"규칙 {status}"),
        condition=[{"position": 1, "lemma": "た"}],
        status=status,
    )


def listed(admin_client, url):
    return {p.name for p in admin_client.get(url).context["cl"].result_list}


def reviewed_pattern(name):
    """모든 것이 승인·반려·폐기된 패턴."""
    done = pattern(name, connection_form="동사 て형", connection_status=APPROVED)
    usage(
        done,
        "승인",
        korean_equivalent="하다",
        korean_equivalent_status=APPROVED,
        function_tags=["perfective"],
        function_tags_status=APPROVED,
    )
    # 반려하면 대응 표현·기능 태그 상태는 그대로 남는다. 용법의 일부라 함께 끝난 것으로 본다.
    usage(
        done,
        "반려",
        status=REJECTED,
        korean_equivalent="해 두다",
        korean_equivalent_status=PENDING,
        function_tags=["perfective"],
        function_tags_status=PENDING,
    )
    rule(done, UsageRule.Status.APPROVED)
    rule(done, UsageRule.Status.RETIRED)
    return done


def test_to_review_keeps_only_patterns_with_something_pending(admin_client):
    pattern("패턴", status=PENDING)
    pattern("접속", connection_form="동사 て형", connection_status=PENDING)
    usage(pattern("용법"), status=PENDING)
    usage(pattern("대응"), korean_equivalent="하다", korean_equivalent_status=PENDING)
    usage(pattern("태그"), function_tags=["perfective"], function_tags_status=PENDING)
    rule(pattern("규칙"), UsageRule.Status.PENDING)
    reviewed_pattern("끝남")
    pattern("반려됨", status=REJECTED)

    assert listed(admin_client, TO_REVIEW) == {"패턴", "접속", "용법", "대응", "태그", "규칙"}
    assert len(listed(admin_client, PATTERNS)) == 8


def text(admin_client, url):
    return html.unescape(admin_client.get(url).content.decode())


def results(admin_client, url):
    """목록 화면의 결과 표 글자. 필터 메뉴에도 같은 상태 이름이 있어 표만 본다."""
    page = text(admin_client, url)
    start = page.index('id="result_list"')
    return page[start : page.index("</table>", start)]


def test_to_review_filter_is_offered_on_the_pattern_list(admin_client):
    assert "검수할 것 있음" in text(admin_client, PATTERNS)


def test_to_review_queries_do_not_grow_with_patterns(admin_client, django_assert_num_queries):
    usage(pattern("하나", status=PENDING), status=PENDING)
    with CaptureQueriesContext(connection) as one:
        admin_client.get(TO_REVIEW)
    for name in ["둘", "셋", "넷"]:
        rule(pattern(name, status=PENDING), UsageRule.Status.PENDING)
        reviewed_pattern(f"{name} 끝남")

    with django_assert_num_queries(len(one)):
        assert admin_client.get(TO_REVIEW).status_code == 200
    assert len(listed(admin_client, TO_REVIEW)) == 4


def test_lists_show_review_states_as_badges(admin_client):
    base = pattern(
        "てしまう", status=PENDING, connection_form="동사 て형", connection_status=APPROVED
    )
    pattern("ちゃう", status=REJECTED, register="colloquial")
    done = usage(
        base,
        "완료",
        status=PENDING,
        korean_equivalent="해 버리다",
        korean_equivalent_status=APPROVED,
    )
    usage(base, "유감", status=REJECTED)
    UsageRule.objects.create(pattern=base, usage=done, condition=[], status="retired")

    patterns = results(admin_client, PATTERNS)
    usages = results(admin_client, "/admin/analysis/grammarusage/")
    rules = results(admin_client, "/admin/analysis/usagerule/")

    for label in ["미검수", "승인", "반려"]:
        assert label in patterns, label
        assert label in usages, label
    assert "폐기" in rules
