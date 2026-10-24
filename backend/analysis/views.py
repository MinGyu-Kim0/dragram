from django.http import HttpResponse, StreamingHttpResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from accounts.tokens import ExtensionTokenAuthentication
from analysis.answers import _is_text
from analysis.models import UsageLog
from analysis.normalize import analysis_text
from analysis.presenter import Presenter
from analysis.rematch import rematch
from analysis.sentence import Sentence
from analysis.stream import _NDJSON, _ndjson, llm_stream
from analysis.usage import RequestUsage
from errors import AnalysisError, BusinessError


# 확장 토큰으로 로그인한 사용자만 쓴다. 토큰이 없거나 쓸 수 없으면 형태소 분석·LLM 전에
# AUTH:LOGIN_REQUIRED로 거부한다(#109).
@api_view(["POST"])
@authentication_classes([ExtensionTokenAuthentication])
@permission_classes([])
def analyze(request):
    """캐시 분석은 한 번에 보내고, 패턴 세트 버전이 올랐으면 다시 매칭하고, 나머지는 작업자의
    LLM 작업을 기다리며 흘려보낸다.
    """
    original = request.data.get("text") if isinstance(request.data, dict) else None
    if not _is_text(original):
        raise BusinessError(AnalysisError.TEXT_REQUIRED, "분석할 문장이 없음")
    text, origins = analysis_text(original)
    presenter = Presenter(Sentence(text), original, origins)
    sentence, user = presenter.sentence, request.user
    cached = sentence.cached
    if cached and cached.matcher_version >= sentence.matcher_version:
        RequestUsage.start(UsageLog.Path.CACHE, user, cached.pk, success=True)
        # 이미 다 있으니 한 번에 보낸다.
        events = [
            presenter.translation_event(cached.translation_ko),
            presenter.analysis_event(cached),
        ]
        return HttpResponse("".join(map(_ndjson, events)), content_type=_NDJSON)
    if cached:
        return rematch(presenter, user)
    return StreamingHttpResponse(
        llm_stream(presenter, user, presenter.early_events()), content_type=_NDJSON
    )
