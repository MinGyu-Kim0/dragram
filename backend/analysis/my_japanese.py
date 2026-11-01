"""내 일본어: 사용자가 사이드 패널 카드에서 추가하거나 숨긴 용법(#313)과 단어 뜻(#314)을 웹에 보인다
(#322, FR-M10). 항목마다 사용자가 고른 예문을 함께 싣는다.

본인 항목만 읽고 LLM을 부르지 않는다. 미검수면 pending이다(ADR 0003). 반려된 용법·패턴·뜻은 내용
없이 ID와 예문만 보낸다({"rejected": true}). 사용자가 그 예문(본인 원문)과 항목을 지울 수 있게 하기
위해서다. 회화체로 만났어도 용법 단위라 원형 패턴 이름으로 보인다.
"""

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.views import SessionUser
from analysis import words
from analysis.models import MyItem, ReviewStatus
from analysis.presenter import _review_status
from errors.auth import AuthError
from errors.base import BusinessError
from errors.my_items import MyItemError


def _my_items(request, kind):
    """로그인한 사용자의 그 종류 항목(?state=added|hidden, 기본 added). 최근에 바꾼 순이다."""
    if not request.user.is_authenticated:
        raise BusinessError(AuthError.LOGIN_REQUIRED, "로그인하지 않은 세션")
    state = request.GET.get("state", MyItem.State.ADDED)
    if state not in MyItem.State.values:
        raise BusinessError(MyItemError.INVALID, "상태가 맞지 않음")
    return (
        MyItem.objects.filter(user=request.user, state=state, **{f"{kind}__isnull": False})
        .prefetch_related("examples")
        .order_by("-updated_at", "-id")
    )


def _examples(item):
    """사용자가 고른 예문(본인 원문). 저장한 순이다."""
    return [
        {"id": e.pk, "text": e.original_text, "start": e.highlight_start, "end": e.highlight_end}
        for e in sorted(item.examples.all(), key=lambda e: e.pk)
    ]


@api_view(["GET"])
@authentication_classes([SessionUser])
@permission_classes([])
def my_grammar(request):
    """내 용법 항목."""
    usages = []
    for item in _my_items(request, "usage").select_related("usage__pattern__variant_of"):
        usage = item.usage
        review_status = _review_status(usage.pattern, usage)
        if review_status is None:
            usages.append({"usage_id": usage.pk, "rejected": True, "examples": _examples(item)})
            continue
        usages.append(
            {
                "usage_id": usage.pk,
                "pattern_name": usage.pattern.name,
                "name": usage.name,
                "explanation_ko": usage.explanation_ko,
                "korean_equivalent": usage.korean_equivalent,
                "korean_equivalent_review_status": usage.korean_equivalent_status,
                "review_status": review_status,
                "examples": _examples(item),
            }
        )
    return Response({"usages": usages})


@api_view(["GET"])
@authentication_classes([SessionUser])
@permission_classes([])
def my_words(request):
    """내 단어 뜻 항목. 모양은 분석 보기의 단어 항목에서 위치를 뺀 것이다."""
    items = []
    for item in _my_items(request, "sense").select_related("sense__word"):
        sense = item.sense
        if sense.sense_status == ReviewStatus.REJECTED:
            items.append({"sense_id": sense.pk, "rejected": True, "examples": _examples(item)})
            continue
        word = words.response_item(None, None, sense.word, sense.word.reading, sense)
        del word["start"], word["end"]
        items.append({"sense_id": sense.pk, **word, "examples": _examples(item)})
    return Response({"words": items})
