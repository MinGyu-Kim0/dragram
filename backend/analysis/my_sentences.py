"""내 기록(#196): 웹 세션으로 본인이 분석한 문장 목록을 보고 문장 하나를 지운다.

원문은 본인 user_id로만 조회한다. 지우는 것은 그 사용자의 user_sentence 행뿐이고, 원문이 없는
공용 분석·번역은 남는다.
"""

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.views import SessionUser, require_csrf
from analysis.models import UserSentence
from errors.auth import AuthError
from errors.base import BusinessError
from errors.sentences import UserSentenceError


def _login_required(request):
    if not request.user.is_authenticated:
        raise BusinessError(AuthError.LOGIN_REQUIRED, "로그인하지 않은 세션")


@api_view(["GET"])
@authentication_classes([SessionUser])
@permission_classes([])
def my_sentences(request):
    """내가 분석한 문장 목록(최근 분석 순)."""
    _login_required(request)
    # shortcut: 페이지 없이 전부 보낸다. 기록이 많아지면 #195에서 페이지를 나눈다.
    rows = UserSentence.objects.filter(user=request.user).order_by("-last_analyzed_at", "-id")
    return Response(
        {
            "sentences": [
                {"id": s.pk, "text": s.original_text, "analyzed_at": s.last_analyzed_at}
                for s in rows
            ]
        }
    )


@api_view(["DELETE"])
@authentication_classes([SessionUser])
@permission_classes([])
def my_sentence(request, sentence_id):
    """내 기록에서 문장 하나를 지운다."""
    require_csrf(request)
    _login_required(request)
    deleted, _ = UserSentence.objects.filter(user=request.user, pk=sentence_id).delete()
    if not deleted:
        raise BusinessError(UserSentenceError.NOT_FOUND, "내 기록에 없는 문장")
    return Response(status=204)
