"""고정 평가 세트로 분석 품질 재기(FR-A26, #177).

평가 문장을 실제 요청처럼 선점·분석·저장하고, 사이드 패널에 보일 문법 항목과 호출·토큰을 평가
결과로 남긴다. 결과는 공용 캐시에도 남는다(관리자가 쓴 문장이라 원문 불변식에 걸리지 않는다,
사용자 결정 2026-10-25). 캐시가 있어도 stale로 돌려 매번 새로 분석한다. 사용자 요청이 아니라
사용 기록의 user는 NULL이고 하루 한도에 들지 않는다.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import F, Sum
from django.utils import timezone

from analysis.models import EvalItem, EvalResult, SentenceAnalysis, SpanMatch, UsageLog
from analysis.normalize import NORMALIZE_VERSION, analysis_text
from analysis.presenter import Presenter
from analysis.sentence import Sentence
from analysis.stream import CLAIM_EXPIRY_SECONDS
from analysis.usage import RequestUsage
from analysis.worker import run_analysis


def _claim(sentence):
    """그 문장의 분석 행을 선점하고 stale로 돌린다. 다른 요청이 처리 중이면 None이다.

    stream.claim과 같은 조건부 선점이지만, 캐시가 있어도 새로 분석하고 큐 대신 이 프로세스에서
    바로 분석한다.
    """
    now = timezone.now()
    processing = SentenceAnalysis.Status.PROCESSING
    row, created = SentenceAnalysis.objects.get_or_create(
        sentence_hash=sentence.sentence_hash,
        defaults={
            "normalize_version": NORMALIZE_VERSION,
            "normalized_length": len(sentence.key_text),
            "status": processing,
            "processing_started_at": now,
        },
    )
    if created:
        return row
    claimed = (
        SentenceAnalysis.objects.filter(pk=row.pk)
        .exclude(
            status=processing,
            processing_started_at__gt=now - timedelta(seconds=CLAIM_EXPIRY_SECONDS),
        )
        .update(
            status=processing,
            processing_started_at=now,
            generation=F("generation") + 1,
            processing_translation_ko=None,
            # 캐시로 보지 않게 해서(Sentence.cached) 처음부터 다시 분석한다.
            is_stale=True,
        )
    )
    if not claimed:
        return None
    row.refresh_from_db()
    return row


def _surface(text, start, end):
    """UTF-16 위치의 글자."""
    return text.encode("utf-16-le")[2 * start : 2 * end].decode("utf-16-le")


def _flat(grammar):
    """응답 문법 항목과 그 구성 문법(parts)을 원문 순서로 편다."""
    items = []
    for item in grammar:
        items.append(item)
        items.extend(item.get("parts", []))
    return sorted(items, key=lambda item: (item["start"], item["end"]))


def evaluate_sentence(run, eval_sentence):
    """평가 문장 하나를 분석해 결과와 항목을 남긴다. 실패도 결과로 남기고 예외를 내지 않는다."""
    result = EvalResult.objects.create(run=run, sentence=eval_sentence, text=eval_sentence.text)
    try:
        _analyze(result)
    except Exception as e:  # noqa: BLE001  한 문장의 실패가 나머지를 막지 않는다.
        _fail(result, type(e).__name__)
    return result


def _fail(result, error):
    result.failed, result.error = True, error
    result.save(update_fields=["failed", "error"])


def _analyze(result):
    original = result.text
    text, origins = analysis_text(original)
    row = _claim(Sentence(text))
    if row is None:
        _fail(result, "다른 요청이 처리 중")
        return
    usage = RequestUsage.start(UsageLog.Path.LLM, None, row.pk)
    try:
        run_analysis(row.pk, text, usage.id, row.processing_started_at)
    finally:
        _count_calls(result, usage.id, row.pk)
    row.refresh_from_db()
    if row.status != SentenceAnalysis.Status.COMPLETE:
        _fail(result, "분석 실패")
        return
    event = Presenter(Sentence(text), original, origins).analysis_event(row)
    result.translation_ko = event["translation_ko"]
    result.save(update_fields=["translation_ko"])
    items = [
        EvalItem(
            result=result,
            start=item["start"],
            end=item["end"],
            surface=_surface(original, item["start"], item["end"]),
            state=item["state"],
            name=item["name"],
            alternatives=[alt["name"] for alt in item.get("alternatives", [])],
            review_status=item["review_status"],
        )
        for item in _flat(event["grammar"])
    ]
    for item in items:
        item.grade = _last_grade(result, item)
    EvalItem.objects.bulk_create(items)


def _last_grade(result, item):
    """같은 평가 문장(고치지 않은 같은 글)의 지난 실행에서 위치·상태·이름·대안이 모두 같은 항목의
    가장 최근 채점. 없으면 미채점이다.
    """
    last = (
        EvalItem.objects.filter(
            result__sentence=result.sentence,
            result__text=result.text,
            start=item.start,
            end=item.end,
            state=item.state,
            name=item.name,
            alternatives=item.alternatives,
        )
        .exclude(result__run=result.run)
        .exclude(grade=EvalItem.Grade.UNGRADED)
        .order_by("-result__run_id", "-id")
        .first()
    )
    return last.grade if last else EvalItem.Grade.UNGRADED


def _count_calls(result, request_id, analysis_id):
    """이 결과의 request 행 뒤에 남은, 그 분석 행의 사용자 없는 LLM 호출을 센다."""
    calls = UsageLog.objects.filter(
        kind=UsageLog.Kind.LLM, analysis_id=analysis_id, user__isnull=True, pk__gt=request_id
    )
    totals = calls.aggregate(
        input=Sum("input_tokens"), cached=Sum("cached_input_tokens"), output=Sum("output_tokens")
    )
    result.calls = calls.count()
    result.input_tokens = totals["input"] or 0
    result.cached_input_tokens = totals["cached"] or 0
    result.output_tokens = totals["output"] or 0
    result.save(update_fields=["calls", "input_tokens", "cached_input_tokens", "output_tokens"])


def _rate(part, whole):
    return part / whole if whole else None


def metrics(run):
    """실행의 지표(FR-A26). 정확도는 채점한 항목만으로 내고 미채점 수를 함께 낸다. LLM
    confidence는 쓰지 않는다. 비용은 단가 설정(백만 토큰당 달러)이 모두 있을 때만 낸다.
    """
    results = list(run.results.all())
    items = list(EvalItem.objects.filter(result__run=run).values_list("state", "grade"))
    grades = [grade for _, grade in items]
    graded = len(grades) - grades.count(EvalItem.Grade.UNGRADED)
    span_right = graded - grades.count(EvalItem.Grade.WRONG_SPAN)
    tokens = {
        key: sum(getattr(r, key) for r in results)
        for key in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    prices = (
        settings.EVAL_PRICE_INPUT,
        settings.EVAL_PRICE_CACHED_INPUT,
        settings.EVAL_PRICE_OUTPUT,
    )
    cost = None
    if None not in prices:
        uncached = tokens["input_tokens"] - tokens["cached_input_tokens"]
        counts = (uncached, tokens["cached_input_tokens"], tokens["output_tokens"])
        cost = sum(n * price for n, price in zip(counts, prices, strict=True)) / 1_000_000
    return {
        "sentences": len(results),
        "failed": sum(r.failed for r in results),
        "items": len(items),
        "ungraded": len(items) - graded,
        "span_accuracy": _rate(span_right, graded + sum(r.missed for r in results)),
        "usage_accuracy": _rate(grades.count(EvalItem.Grade.CORRECT), span_right),
        "ambiguous_rate": _rate(grades.count(EvalItem.Grade.AMBIGUOUS), span_right),
        "unresolved_rate": _rate(
            sum(state == SpanMatch.State.UNRESOLVED for state, _ in items), len(items)
        ),
        "calls_per_sentence": _rate(sum(r.calls for r in results), len(results)),
        **tokens,
        "cost_usd": cost,
    }
