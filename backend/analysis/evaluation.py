"""고정 평가 세트로 분석 품질 재기(FR-A26, #177).

평가 문장을 실제 요청처럼 선점·분석·저장하고, 사이드 패널에 보일 문법 항목과 호출·토큰을 평가
결과로 남긴다. 결과는 공용 캐시에도 남는다(관리자가 쓴 문장이라 원문 불변식에 걸리지 않는다,
사용자 결정 2026-10-25). 캐시가 있어도 stale로 돌려 매번 새로 분석하고, 분석이 실패하면 원래
캐시를 되살린다. 사용자 요청이 아니라 사용 기록의 user는 NULL이고 하루 한도에 들지 않는다.
"""

from django.conf import settings
from django.db.models import Sum

from analysis.models import EvalItem, EvalResult, SentenceAnalysis, SpanMatch, UsageLog
from analysis.normalize import analysis_text
from analysis.presenter import Presenter
from analysis.sentence import Sentence
from analysis.stream import take
from analysis.usage import RequestUsage
from analysis.worker import run_analysis
from errors import BusinessError
from errors.handler import log_business_error


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
    """평가 문장 하나를 분석해 결과와 항목을 남긴다. 분석 실패(BusinessError)도 결과로 남기고
    다음 문장으로 넘어간다. 그 밖의 예외는 우리 코드의 버그라 그대로 올린다.
    """
    result = EvalResult.objects.create(run=run, sentence=eval_sentence, text=eval_sentence.text)
    try:
        _analyze(result)
    except BusinessError as e:
        log_business_error(e)
        _fail(result, e.error_code.code)
    return result


def _fail(result, error):
    result.failed, result.error = True, error
    result.save(update_fields=["failed", "error"])


def _is_fresh(row):
    return (
        row.status == SentenceAnalysis.Status.COMPLETE
        and row.word_spans is not None
        and not row.is_stale
    )


def _analyze(result):
    original = result.text
    text, origins = analysis_text(original)
    sentence = Sentence(text)
    before = sentence.existing
    row, claimed = take(sentence, again=True)
    if not claimed:
        _fail(result, "다른 요청이 처리 중")
        return
    # 읽은 뒤 선점 하나로만 세대 번호가 올랐으면 그사이 무효화(반려 등)가 없었다.
    restorable = (
        before is not None and _is_fresh(before) and row.generation == before.generation + 1
    )
    usage = RequestUsage.start(UsageLog.Path.LLM, None, row.pk)
    result.usage_request_id = usage.id
    result.save(update_fields=["usage_request"])
    try:
        run_analysis(row.pk, text, usage.id, row.processing_started_at)
    finally:
        _count_calls(result, usage.id, row.pk)
    if not SentenceAnalysis.objects.filter(
        pk=row.pk, status=SentenceAnalysis.Status.COMPLETE
    ).exists():
        if restorable:
            # 실패한 시도는 저장하지 않아 옛 결과가 그대로다. 그사이 다른 요청이 다시 선점하거나
            # 무효화하지 않았으면 정상 캐시로 되돌려, 다음 사용자가 LLM을 다시 부르지 않게 한다.
            SentenceAnalysis.objects.filter(
                pk=row.pk, generation=row.generation, status=SentenceAnalysis.Status.FAILED
            ).update(status=SentenceAnalysis.Status.COMPLETE, is_stale=False)
        _fail(result, "분석 실패")
        return
    row.refresh_from_db()
    presenter = Presenter(Sentence(text), original, origins)
    grammar, spans = presenter.grammar_spans(row)
    items = []
    for item in _flat(grammar):
        span = spans[id(item)]
        items.append(
            EvalItem(
                result=result,
                start=item["start"],
                end=item["end"],
                surface=_surface(original, item["start"], item["end"]),
                state=item["state"],
                name=item["name"],
                pattern_name=span.pattern.name,
                pattern_ref=span.pattern_id,
                usage_ref=span.usage_id,
                alternatives=[alt["name"] for alt in item.get("alternatives", [])],
                review_status=item["review_status"],
            )
        )
    for item in items:
        item.grade = _last_grade(result, item)
    EvalItem.objects.bulk_create(items)
    result.translation_ko = presenter.sentence.restore(row.translation_ko)
    result.missed = _last_missed(result, items)
    result.save(update_fields=["translation_ko", "missed"])


def _key(item):
    """채점을 이어받는 기준: 위치·상태·패턴·용법·대안"""
    return (
        item.start,
        item.end,
        item.state,
        item.pattern_ref,
        item.usage_ref,
        tuple(item.alternatives),
    )


def _last_missed(result, items):
    """같은 평가 문장(고치지 않은 같은 글)의 가장 최근 결과가 항목까지 똑같으면 그 놓친 문법 수.
    다르거나 아직 적지 않았으면 None(아직 안 적음)이다.
    """
    last = (
        EvalResult.objects.filter(sentence=result.sentence, text=result.text, failed=False)
        .exclude(run=result.run)
        .order_by("-run_id")
        .first()
    )
    if last is None or sorted(map(_key, last.items.all())) != sorted(map(_key, items)):
        return None
    return last.missed


def _last_grade(result, item):
    """같은 평가 문장(고치지 않은 같은 글)의 지난 실행에서 위치·상태·패턴·용법·대안이 모두 같은
    항목의 가장 최근 채점. 없으면 미채점이다.
    """
    last = (
        EvalItem.objects.filter(
            result__sentence=result.sentence,
            result__text=result.text,
            start=item.start,
            end=item.end,
            state=item.state,
            pattern_ref=item.pattern_ref,
            usage_ref=item.usage_ref,
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
    """실행의 지표(FR-A26). 정확도는 채점한 항목과 적어 둔 놓친 문법 수만으로 내고, 미채점
    항목 수와 놓친 문법 수를 아직 적지 않은 문장 수를 함께 낸다. LLM
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
        "missed_unchecked": sum(r.missed is None for r in results if not r.failed),
        "span_accuracy": _rate(span_right, graded + sum(r.missed or 0 for r in results)),
        "usage_accuracy": _rate(grades.count(EvalItem.Grade.CORRECT), span_right),
        "ambiguous_rate": _rate(grades.count(EvalItem.Grade.AMBIGUOUS), span_right),
        "unresolved_rate": _rate(
            sum(state == SpanMatch.State.UNRESOLVED for state, _ in items), len(items)
        ),
        "calls_per_sentence": _rate(sum(r.calls for r in results), len(results)),
        **tokens,
        "cost_usd": cost,
    }
