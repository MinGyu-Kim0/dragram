from asgiref.sync import sync_to_async
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from accounts.tokens import ExtensionTokenAuthentication
from analysis import limits, user_sentences
from analysis.answers import _is_text
from analysis.models import SentenceAnalysis, UsageLog
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
    """사용자의 동시 분석 요청 셈에 넣고 분석한다(#28). 응답이 끝나면(스트림은 정상·오류·연결
    끊김 모두) 셈에서 뺀다. 상한을 넘으면 형태소 분석 전에 거부한다.
    """
    leave = limits.enter(request.user)
    try:
        response = _analyze(request)
    except BaseException:
        leave()
        raise
    if response.streaming:
        response.streaming_content = _leaving(response.streaming_content, leave)
    else:
        leave()
    return response


async def _leaving(content, leave):
    try:
        async for part in content:
            yield part
    finally:
        # 동기 Redis 호출이 이벤트 루프의 다른 요청을 막지 않게 다른 스레드에서 뺀다.
        await sync_to_async(leave, thread_sensitive=False)()


def _analyze(request):
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
        user_sentences.record(user, presenter.original, cached.pk)
        return HttpResponse("".join(map(_ndjson, events)), content_type=_NDJSON)
    if cached:
        return rematch(presenter, user)
    # 다른 요청의 작업에 붙는 요청은 비용이 없어 막지 않는다. 확인한 뒤 상태가 바뀌는 경쟁은 둔다.
    joining = sentence.existing is not None and (
        sentence.existing.status == SentenceAnalysis.Status.PROCESSING
    )
    if not joining and limits.over_limit(user):
        raise BusinessError(AnalysisError.USAGE_LIMIT, "하루 토큰 한도를 넘음")
    return StreamingHttpResponse(
        llm_stream(presenter, user, presenter.early_events()), content_type=_NDJSON
    )
