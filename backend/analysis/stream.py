"""요청이 분석 작업을 선점하고 작업 소식을 구독해 흘려보내는 스트림(#98, ADR 0005)."""

import json
import logging
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db.models import F
from django.utils import timezone

from analysis import jobs, user_sentences
from analysis.models import SentenceAnalysis, UsageLog
from analysis.normalize import NORMALIZE_VERSION
from analysis.sentence import _is_fresh
from analysis.usage import RequestUsage
from analysis.worker import _attempt, _fail
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error

logger = logging.getLogger(__name__)


# 응답은 줄 단위 JSON(한 줄에 이벤트 하나)이다(#27).
# translation(번역, 루비) → analysis(번역, 문법, 단어) 순서다. 새 문장은 translation 앞에
# translation_partial(검증 전 번역 앞부분, #303)이 여럿 올 수 있고, 그 사이에 judged(첫 LLM
# 응답이 판정한 문법, 고른 뜻)가 올 수 있다(#97). 형태소 분석 등 응답을 시작하기 전의
# 실패는 다른 API 오류처럼 상태 코드로, 큐 넣기·작업자의 LLM 작업 실패는 error 이벤트로 알린다(#98).
_NDJSON = "application/x-ndjson"


def _ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


# 요청이 작업 소식을 기다리는 상한. 작업 시간 제한(jobs.JOB_TIMEOUT_SECONDS)보다 길고, 큐에 넣은
# 때부터 세므로 큐 대기도 포함한다. 넘으면 error 이벤트로 닫고, 작업은 계속된다(ADR 0005).
WAIT_SECONDS = 130
# 이만큼 지난 처리 중 행은 작업자가 죽은 것으로 보고 다음 요청이 다시 선점한다(#99). 작업 시간
# 제한(120초)과 요청 대기(130초)보다 길다.
CLAIM_EXPIRY_SECONDS = 150


def claim(sentence, user):
    """이 문장의 LLM 작업을 선점한다. 구독한 뒤에 부른다(ADR 0005).

    (상태, 분석 행, 사용 기록)이다. 상태는 claimed(이 요청이 선점해 작업을 넣음),
    processing(다른 요청의 작업을 기다림), saved(그사이 다른 요청의 작업이 저장을 마침)다.
    처리 중이 아니거나 선점이 만료됐고(#99), 다시 분석해야 하는 행만 조건부 UPDATE로 선점하고,
    선점할 때마다 세대 번호를 올린다. 새 문장은 처리 중 행을 먼저 만들어, 실패한 시도의 LLM 사용
    기록도 그 행에 잇는다.
    """
    row, claimed = take(sentence)
    if not claimed and _is_fresh(row):
        return "saved", row, RequestUsage.start(UsageLog.Path.CACHE, user, row.pk, True)
    usage = RequestUsage.start(UsageLog.Path.LLM, user, row.pk)
    if claimed:
        try:
            jobs.enqueue_analysis(row.pk, sentence.text, usage.id, row.processing_started_at)
        except BaseException:
            # 큐에 넣지 못했으면 선점을 풀어, 다음 요청이 처리 중 행에 붙잡히지 않게 한다.
            _fail(row.pk, row.processing_started_at, AnalysisError.FAILED.code)
            raise
    return "claimed" if claimed else "processing", row, usage


def take(sentence, again=False):
    """처리 중이 아니거나 선점이 만료된 분석 행을 조건부 UPDATE로 선점한다. (분석 행, 선점했는가)다.

    다시 분석해야 하는 행만 선점하고, 선점할 때마다 세대 번호를 올린다. 새 문장은 처리 중 행을
    먼저 만든다. again이면 캐시로 쓸 수 있는 행도 stale로 돌려 선점한다(평가 실행, #177).
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
        now = timezone.now()
        rows = SentenceAnalysis.objects.filter(pk=row.pk).exclude(
            status=processing,
            processing_started_at__gt=now - timedelta(seconds=CLAIM_EXPIRY_SECONDS),
        )
        if not again:
            rows = rows.exclude(word_spans__isnull=False, is_stale=False)
        claimed = (
            rows.update(
                status=processing,
                processing_started_at=now,
                generation=F("generation") + 1,
                processing_translation_ko=None,
                # 캐시로 보지 않게 해서(Sentence.cached) 처음부터 다시 분석한다.
                **({"is_stale": True} if again else {}),
            )
            == 1
        )
        row.refresh_from_db()
    return row, claimed


def saved_events(presenter, user, row, translated):
    """작업이 저장한 행의 이벤트. 번역을 아직 보내지 않았으면 함께 보낸다. 분석 기록도 남긴다."""
    row, event = presenter.locked_analysis_event(row.pk)
    events = [] if translated else [presenter.translation_event(row.translation_ko)]
    events.append(event)
    user_sentences.record(user, presenter.original, row.pk, events[-1]["words"])
    return events


async def llm_stream(presenter, user, early):
    """LLM 작업을 기다리는 요청의 이벤트(ADR 0005).

    DB만으로 정해지는 이벤트를 먼저 보내고, 작업 소식을 구독한 뒤 선점하거나 처리 중인 작업에
    붙는다. 번역 소식이 오면 번역을, 저장 소식이 오면 저장된 행으로 만든 analysis를 보낸다.
    늦게 붙은 요청은 작업이 먼저 저장한 번역부터 보낸다. 큐 넣기 실패, 실패 소식, 대기 상한이면
    error다.
    """
    async with jobs.listen(presenter.sentence.sentence_hash) as pubsub:
        for event in early:
            yield _ndjson(event)
        try:
            state, row, request_usage = await sync_to_async(claim)(presenter.sentence, user)
        except BusinessError as e:
            # 선점은 claim이 풀고 기다리던 요청에 실패 소식도 보냈다.
            log_business_error(e)
            yield _ndjson({"type": "error", "error": e.error_code.code})
            return
        if state == "saved":
            for event in await sync_to_async(saved_events)(presenter, user, row, False):
                yield _ndjson(event)
            return
        translated = state == "processing" and row.processing_translation_ko is not None
        if translated:
            yield _ndjson(presenter.translation_event(row.processing_translation_ko))
        error = AnalysisError.FAILED.code
        attempt = _attempt(row.processing_started_at)
        # 마지막으로 보낸 번역 앞부분 이벤트
        shown = None
        async for message in jobs.messages(pubsub, WAIT_SECONDS):
            if message.get("attempt") != attempt:
                continue
            if message["type"] == "translation_partial":
                event = (
                    None
                    if translated
                    else presenter.partial_translation_event(message["translation_ko"])
                )
                # 자른 앞부분이 그대로면 다시 보내지 않는다.
                if event is not None and event != shown:
                    shown = event
                    yield _ndjson(event)
                continue
            if message["type"] == "translation":
                if not translated:
                    translated = True
                    yield _ndjson(presenter.translation_event(message["translation_ko"]))
                continue
            if message["type"] == "judged":
                event = await sync_to_async(presenter.judged_event)(
                    message["spans"], message["word_spans"]
                )
                yield _ndjson(event)
                continue
            if message["type"] == "done":
                row = await sync_to_async(SentenceAnalysis.objects.get)(pk=row.pk)
                if row.word_spans is not None:
                    for event in await sync_to_async(saved_events)(
                        presenter, user, row, translated
                    ):
                        yield _ndjson(event)
                    await sync_to_async(request_usage.succeed)()
                    return
            else:
                error = message["error"]
            break
        else:
            logger.warning("분석 작업 대기 시간 초과: analysis_id=%s", row.pk)
        yield _ndjson({"type": "error", "error": error})
