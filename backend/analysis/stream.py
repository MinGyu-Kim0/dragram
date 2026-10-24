"""요청이 분석 작업을 선점하고 작업 소식을 구독해 흘려보내는 스트림(#98, ADR 0005)."""

import json
import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from django.db.models import F
from django.utils import timezone

from analysis import jobs
from analysis.models import SentenceAnalysis, UsageLog
from analysis.normalize import NORMALIZE_VERSION
from analysis.sentence import _is_fresh
from analysis.usage import RequestUsage
from analysis.worker import _attempt, _fail
from errors import AnalysisError

logger = logging.getLogger(__name__)


# 응답은 줄 단위 JSON(한 줄에 이벤트 하나)이다(#27).
# translation(번역, 루비) → analysis(번역, 문법, 단어) 순서다. 형태소 분석 등 응답을 시작하기 전의
# 실패는 다른 API 오류처럼 상태 코드로, 작업자의 LLM 작업 실패는 error 이벤트로 알린다(#98).
_NDJSON = "application/x-ndjson"


def _ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


# 요청이 작업 소식을 기다리는 상한. 작업 시간 제한(jobs.JOB_TIMEOUT_SECONDS)보다 길고, 큐에 넣은
# 때부터 세므로 큐 대기도 포함한다. 넘으면 error 이벤트로 닫고, 작업은 계속된다(ADR 0005).
WAIT_SECONDS = 130


def _in_thread(events):
    """동기 이벤트 생성기를 비동기 스트림으로 흘려보낸다(재매칭).

    다음 이벤트는 요청 스레드가 아닌 스레드에서 만든다. ASGI에서는 동기 코드가 한 스레드에서 돌아
    LLM을 기다리는 동안 다른 요청까지 막기 때문이다. 이벤트 사이에 걸친 트랜잭션이 없어 이벤트마다
    그 스레드의 DB 연결을 정리한다.
    """
    inline = settings.ANALYSIS_INLINE

    def step():
        try:
            return next(events, None)
        finally:
            if not inline:
                close_old_connections()

    async def stream():
        while (event := await sync_to_async(step, thread_sensitive=inline)()) is not None:
            yield _ndjson(event)

    return stream()


def claim(sentence, user):
    """이 문장의 LLM 작업을 선점한다. 구독한 뒤에 부른다(ADR 0005).

    (상태, 분석 행, 사용 기록)이다. 상태는 claimed(이 요청이 선점해 작업을 넣음),
    processing(다른 요청의 작업을 기다림), saved(그사이 다른 요청의 작업이 저장을 마침)다.
    처리 중이 아니고 다시 분석해야 하는 행만 조건부 UPDATE로 선점하고, 선점할 때마다 세대
    번호를 올린다. 새 문장은 처리 중 행을 먼저 만들어, 실패한 시도의 LLM 사용 기록도 그 행에
    잇는다.
    """
    processing = SentenceAnalysis.Status.PROCESSING
    row, claimed = SentenceAnalysis.objects.get_or_create(
        sentence_hash=sentence.sentence_hash,
        defaults={
            "normalize_version": NORMALIZE_VERSION,
            "normalized_length": len(sentence.key_text),
            "status": processing,
            "processing_started_at": timezone.now(),
        },
    )
    if not claimed:
        claimed = (
            SentenceAnalysis.objects.filter(pk=row.pk)
            .exclude(status=processing)
            .exclude(word_spans__isnull=False, is_stale=False)
            .update(
                status=processing,
                processing_started_at=timezone.now(),
                generation=F("generation") + 1,
                processing_translation_ko=None,
            )
        ) == 1
        row.refresh_from_db()
    if not claimed and _is_fresh(row):
        return "saved", row, RequestUsage.start(UsageLog.Path.CACHE, user, row.pk, True)
    usage = RequestUsage.start(UsageLog.Path.LLM, user, row.pk)
    if claimed:
        try:
            jobs.enqueue_analysis(row.pk, sentence.text, usage.id)
        except BaseException:
            # 큐에 넣지 못했으면 선점을 풀어, 다음 요청이 처리 중 행에 붙잡히지 않게 한다.
            _fail(row.pk, row.processing_started_at, AnalysisError.FAILED.code)
            raise
    return "claimed" if claimed else "processing", row, usage


def saved_events(presenter, row, translated):
    """작업이 저장한 행의 이벤트. 번역을 아직 보내지 않았으면 함께 보낸다."""
    events = [] if translated else [presenter.translation_event(row.translation_ko)]
    return [*events, presenter.analysis_event(row)]


async def llm_stream(presenter, user, early):
    """LLM 작업을 기다리는 요청의 이벤트(ADR 0005).

    DB만으로 정해지는 이벤트를 먼저 보내고, 작업 소식을 구독한 뒤 선점하거나 처리 중인 작업에
    붙는다. 번역 소식이 오면 번역을, 저장 소식이 오면 저장된 행으로 만든 analysis를 보낸다.
    늦게 붙은 요청은 작업이 먼저 저장한 번역부터 보낸다. 실패 소식이나 대기 상한이면 error다.
    """
    async with jobs.listen(presenter.sentence.sentence_hash) as pubsub:
        for event in early:
            yield _ndjson(event)
        state, row, request_usage = await sync_to_async(claim)(presenter.sentence, user)
        if state == "saved":
            for event in await sync_to_async(saved_events)(presenter, row, False):
                yield _ndjson(event)
            return
        translated = state == "processing" and row.processing_translation_ko is not None
        if translated:
            yield _ndjson(presenter.translation_event(row.processing_translation_ko))
        error = AnalysisError.FAILED.code
        attempt = _attempt(row.processing_started_at)
        async for message in jobs.messages(pubsub, WAIT_SECONDS):
            if message.get("attempt") != attempt:
                continue
            if message["type"] == "translation":
                if not translated:
                    translated = True
                    yield _ndjson(presenter.translation_event(message["translation_ko"]))
                continue
            if message["type"] == "done":
                row = await sync_to_async(SentenceAnalysis.objects.get)(pk=row.pk)
                if row.word_spans is not None:
                    for event in await sync_to_async(saved_events)(presenter, row, translated):
                        yield _ndjson(event)
                    await sync_to_async(request_usage.succeed)()
                    return
            else:
                error = message["error"]
            break
        else:
            logger.warning("분석 작업 대기 시간 초과: analysis_id=%s", row.pk)
        yield _ndjson({"type": "error", "error": error})
