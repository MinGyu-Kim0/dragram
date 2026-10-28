"""내 기록: 웹 세션으로 본인이 분석한 문장 목록과 저장된 분석을 보고(#195), 문장 하나를
지운다(#196).

원문은 본인 user_id로만 조회한다. 지우는 것은 그 사용자의 user_sentence 행뿐이고, 원문이 없는
공용 분석·번역은 남는다. 저장된 분석을 볼 때는 LLM을 부르지 않는다.
"""

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.views import SessionUser, require_csrf
from analysis import limits
from analysis.models import UserSentence
from analysis.normalize import analysis_text
from analysis.presenter import Presenter
from analysis.sentence import Sentence
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
    # shortcut: 페이지 없이 전부 보낸다. 기록이 많아져 목록이 느려지면 페이지를 나눈다.
    rows = UserSentence.objects.filter(user=request.user).order_by("-last_analyzed_at", "-id")
    return Response(
        {
            "sentences": [
                {"id": s.pk, "text": s.original_text, "analyzed_at": s.last_analyzed_at}
                for s in rows
            ]
        }
    )


@api_view(["GET", "DELETE"])
@authentication_classes([SessionUser])
@permission_classes([])
def my_sentence(request, sentence_id):
    """GET은 내 기록의 문장 하나와 저장된 분석, DELETE는 그 문장을 지운다."""
    if request.method == "GET":
        return _detail(request, sentence_id)
    require_csrf(request)
    _login_required(request)
    deleted, _ = UserSentence.objects.filter(user=request.user, pk=sentence_id).delete()
    if not deleted:
        raise BusinessError(UserSentenceError.NOT_FOUND, "내 기록에 없는 문장")
    return Response(status=204)


def _detail(request, sentence_id):
    """확장의 캐시 응답과 같은 모양(analysis 이벤트 + 루비)으로 저장된 분석을 보인다. 위치는 이
    원문 기준으로 다시 계산하고, 검수 상태는 볼 때마다 정한다(반려된 지식은 빠진다).
    """
    _login_required(request)
    sentence = (
        UserSentence.objects.select_related("analysis")
        .filter(user=request.user, pk=sentence_id)
        .first()
    )
    if sentence is None:
        raise BusinessError(UserSentenceError.NOT_FOUND, "내 기록에 없는 문장")
    # 형태소 분석·패턴 매칭을 다시 하므로 분석 API와 같은 사용자별 동시 요청 셈에 넣는다.
    leave = limits.enter(request.user)
    try:
        text, origins = analysis_text(sentence.original_text)
        presenter = Presenter(Sentence(text), sentence.original_text, origins)
        if presenter.sentence.sentence_hash != sentence.analysis.sentence_hash:
            raise BusinessError(UserSentenceError.OUTDATED, "기록의 분석 키가 지금 원문과 다름")
        event = presenter.analysis_event(sentence.analysis)
    finally:
        leave()
    del event["type"]
    return Response(
        {
            "id": sentence.pk,
            "text": sentence.original_text,
            "analyzed_at": sentence.last_analyzed_at,
            **event,
            "ruby": presenter.ruby,
        }
    )
