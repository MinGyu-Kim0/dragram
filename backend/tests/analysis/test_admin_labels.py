"""관리 화면은 상태와 칸 이름을 한국어로 보이고, 용법의 대응 표현·기능 태그 검수 상태를
드러낸다(#451).
"""

import html
import re
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils.text import capfirst

from analysis.models import (
    EvalItem,
    EvalResult,
    EvalRun,
    EvalSentence,
    GrammarPattern,
    GrammarUsage,
    MatchCorrection,
    PatternMorpheme,
    ReviewStatus,
    UsageLog,
    UsageRule,
    Word,
    WordSense,
)
from tests.analysis.helpers import act, add_word

pytestmark = pytest.mark.django_db

ADMIN = "/admin/analysis/"

# 한국어 이름이 없으면 Django가 보이는 영어 이름: 상태 값(코드 이름에서 만든 label)과 저장 값
STATE_CODES = [
    "Pending",
    "Approved",
    "Rejected",
    "Retired",
    "Standard",
    "Colloquial",
    "Llm",
    "Admin",
    "Jmdict",
    "Dictionary",
    "Ai",
    "Reviewed",
    "Failed",
    "Request",
    "Cache",
    "Db",
    "First Response",
    "Usage Fill",
    "Decided",
    "Divergent",
    "Unresolved",
    "decided",
    "divergent",
    "unresolved",
    "pending",
    "approved",
]
MODELS = [
    GrammarPattern,
    PatternMorpheme,
    GrammarUsage,
    UsageRule,
    Word,
    WordSense,
    MatchCorrection,
    UsageLog,
    EvalSentence,
    EvalRun,
    EvalResult,
    EvalItem,
]
# 칸 이름이 없으면 Django가 칸 이름에서 만드는 영어 이름("Is active" 등)
FIELD_NAMES = sorted(
    {
        capfirst(field.name.replace("_", " "))
        for model in MODELS
        for field in model._meta.concrete_fields
        if not field.auto_created
    }
)


def english(page):
    """화면 글자로 보이는 영어 상태 코드와 영어 칸 이름. 「완료」(Pending)처럼 괄호 안도 본다."""
    text = html.unescape(page.content.decode())
    words = [*STATE_CODES, *FIELD_NAMES]
    return [word for word in words if re.search(rf"[>(]\s*{re.escape(word)}:?\s*[<)]", text)]


def pattern(name, key, **fields):
    defaults = {"is_active": True, "status": ReviewStatus.PENDING}
    return GrammarPattern.objects.create(name=name, morpheme_key=key * 64, **defaults | fields)


def usage(of, name, **fields):
    defaults = {"explanation_ko": "설명", "status": ReviewStatus.PENDING, "origin": "llm"}
    return GrammarUsage.objects.create(pattern=of, name=name, **defaults | fields)


@pytest.fixture
def knowledge():
    """화면마다 여러 상태가 보이도록 채운 지식."""
    base = pattern(
        "てしまう",
        "a",
        status=ReviewStatus.APPROVED,
        connection_form="동사 て형",
        connection_status=ReviewStatus.PENDING,
    )
    PatternMorpheme.objects.create(pattern=base, seq=0, lemma="てしまう", pos1="動詞")
    variant = pattern(
        "ちゃう", "b", is_active=False, status=ReviewStatus.REJECTED, register="colloquial"
    )
    done = usage(
        base,
        "완료",
        korean_equivalent="해 버리다",
        korean_equivalent_filled=True,
        korean_equivalent_status=ReviewStatus.PENDING,
        function_tags=["perfective"],
        function_tags_filled=True,
        function_tags_status=ReviewStatus.APPROVED,
    )
    usage(base, "유감", status=ReviewStatus.REJECTED, origin="admin")
    rule = UsageRule.objects.create(
        pattern=base, usage=done, condition=[{"position": 1, "lemma": "た"}], status="retired"
    )
    word = add_word(None, ["推し"], ["おし"], [(["fave"], [], None), (["idol"], [], None)])
    first, second = word.senses.order_by("id")
    WordSense.objects.filter(pk=first.pk).update(
        sense_origin="llm", sense_status="pending", meaning_ko="최애", meaning_source="llm"
    )
    WordSense.objects.filter(pk=second.pk).update(
        sense_origin="llm",
        sense_status="rejected",
        meaning_ko="아이돌",
        meaning_source="admin",
        meaning_status="reviewed",
    )
    jmdict = add_word(7, ["学生"], ["がくせい"], [(["student"], [], None)])
    jmdict.senses.update(meaning_source="dictionary", meaning_status="failed")
    request = UsageLog.objects.create(kind="request", path="cache", success=True)
    UsageLog.objects.create(kind="request", path="db", success=True)
    call = UsageLog.objects.create(kind="llm", purpose="first_response", success=False)
    UsageLog.objects.create(kind="llm", purpose="usage_fill", success=True)
    return {
        "base": base,
        "variant": variant,
        "usage": done,
        "rule": rule,
        "word": word,
        "sense": first,
        "request": request,
        "call": call,
    }


def pages(k):
    return [
        f"{ADMIN}grammarpattern/",
        f"{ADMIN}grammarpattern/{k['base'].pk}/change/",
        f"{ADMIN}grammarpattern/{k['variant'].pk}/change/",
        f"{ADMIN}grammarusage/",
        f"{ADMIN}grammarusage/{k['usage'].pk}/change/",
        f"{ADMIN}usagerule/",
        f"{ADMIN}usagerule/{k['rule'].pk}/change/",
        # 미검수 규칙은 조건·예문을 폼으로 고친다.
        f"{ADMIN}usagerule/add/",
        f"{ADMIN}word/",
        f"{ADMIN}word/{k['word'].pk}/change/",
        f"{ADMIN}wordsense/",
        f"{ADMIN}wordsense/{k['sense'].pk}/change/",
        f"{ADMIN}usagelog/",
        f"{ADMIN}usagelog/{k['request'].pk}/change/",
        f"{ADMIN}usagelog/{k['call'].pk}/change/",
        f"{ADMIN}matchcorrection/",
        ADMIN,
    ]


def test_admin_pages_show_states_and_field_names_in_korean(admin_client, knowledge):
    for url in pages(knowledge):
        page = admin_client.get(url)

        assert page.status_code == 200, url
        assert english(page) == [], url


def test_admin_pages_show_korean_state_names(admin_client, knowledge):
    text = "".join(
        html.unescape(admin_client.get(url).content.decode()) for url in pages(knowledge)
    )

    for label in [
        "미검수",
        "승인",
        "반려",
        "폐기",
        "회화체",
        "관리자",
        "AI 번역",
        "검수됨",
        "생성 실패",
        "사전",
        "캐시",
        "첫 응답",
        "용법 채우기",
    ]:
        assert label in text, label


def test_refused_action_shows_the_state_in_korean(admin_client, knowledge):
    response = act(admin_client, f"{ADMIN}grammarpattern/", "approve", knowledge["variant"])

    page = html.unescape(response.content.decode())
    assert "지금 상태(반려)에서는 할 수 없습니다" in page
    knowledge["variant"].refresh_from_db()
    assert knowledge["variant"].status == ReviewStatus.REJECTED


def test_refused_rule_action_shows_the_state_in_korean(admin_client, knowledge):
    response = act(admin_client, f"{ADMIN}usagerule/", "approve", knowledge["rule"])

    assert "지금 상태(폐기)에서는 할 수 없습니다" in html.unescape(response.content.decode())


def listed(admin_client, query):
    page = admin_client.get(f"{ADMIN}grammarusage/?{query}")
    return [usage.name for usage in page.context["cl"].result_list]


def test_usages_are_filtered_by_korean_equivalent_and_function_tag_review_state(admin_client):
    base = pattern("ている", "c")
    usage(
        base,
        "진행",
        korean_equivalent="하고 있다",
        korean_equivalent_status=ReviewStatus.PENDING,
        function_tags=["progressive"],
        function_tags_status=ReviewStatus.APPROVED,
    )
    usage(
        base,
        "결과",
        korean_equivalent="해 있다",
        korean_equivalent_status=ReviewStatus.APPROVED,
        function_tags=["resultative"],
        function_tags_status=ReviewStatus.PENDING,
    )
    usage(base, "습관")

    filters = admin_client.get(f"{ADMIN}grammarusage/").context["cl"].filter_specs
    assert {"대응 표현 검수 상태", "기능 태그 검수 상태"} <= {spec.title for spec in filters}
    assert listed(admin_client, "korean_equivalent_status__exact=pending") == ["진행"]
    assert listed(admin_client, "function_tags_status__exact=pending") == ["결과"]


def test_usage_list_and_page_show_korean_equivalent_and_function_tag_review_state(
    admin_client, knowledge
):
    for url in [
        f"{ADMIN}grammarusage/",
        f"{ADMIN}grammarusage/{knowledge['usage'].pk}/change/",
    ]:
        text = html.unescape(admin_client.get(url).content.decode())

        assert "대응 표현 검수 상태" in text, url
        assert "기능 태그 검수 상태" in text, url


@pytest.fixture
def eval_result():
    run = EvalRun.objects.create(status=EvalRun.Status.COMPLETE)
    sentence = EvalSentence.objects.create(text="走っている", category="normal")
    result = EvalResult.objects.create(run=run, sentence=sentence, text="走っている")
    for state, review_status in [
        ("decided", "approved"),
        ("divergent", "pending"),
        ("unresolved", "pending"),
    ]:
        EvalItem.objects.create(
            result=result,
            start=0,
            end=1,
            surface="走",
            pattern_name="패턴",
            pattern_ref=1,
            state=state,
            name="이름",
            review_status=review_status,
        )
    return result


def test_eval_result_page_shows_item_states_in_korean(admin_client, eval_result):
    page = admin_client.get(f"{ADMIN}evalresult/{eval_result.pk}/change/")

    text = html.unescape(page.content.decode())
    for label in ["용법 정해짐", "해석 갈림", "미확정", "승인", "미검수"]:
        assert label in text, label
    assert english(page) == []
    assert admin_client.get(f"{ADMIN}evalresult/").status_code == 200
    assert english(admin_client.get(f"{ADMIN}evalrun/")) == []
    assert english(admin_client.get(f"{ADMIN}evalsentence/")) == []


def test_label_migration_changes_no_stored_value():
    out = StringIO()

    call_command("sqlmigrate", "analysis", "0036", stdout=out)

    statements = [
        line
        for line in out.getvalue().splitlines()
        if line.strip() and not line.startswith("--") and line not in ("BEGIN;", "COMMIT;")
    ]
    assert statements == []
