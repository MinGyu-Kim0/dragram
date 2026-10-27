"""패턴 세트 버전이 오른 캐시 분석의 재매칭(#41)과, 후보가 늘어난 저장 구간의 재판정(#176).

LLM 재판정은 요청이 아닌 작업자(run_rematch)가 한다(#114). 같은 문장·패턴 세트 버전(과 다시 판정할
저장 구간의 후보 상태)의 재판정은
Redis 잠금을 잡은 요청만 큐에 넣고, 다른 요청은 그 시도의 소식을 기다린다. 재판정 잠금은 첫
분석·stale 재분석의 선점과 따로 두며 그 선점을 막지 않는다.
"""

import contextlib
import hashlib
import json
import logging
import uuid

import redis
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction
from django.http import HttpResponse, StreamingHttpResponse

from analysis import jobs, limits, llm, patterns, stream, user_sentences
from analysis.answers import FIRST_VERDICTS, _validate_recheck_answers, reject_quotes
from analysis.examples import _check_examples
from analysis.models import GrammarPattern, GrammarUsage, SentenceAnalysis, SpanMatch, UsageLog
from analysis.presenter import _review_status, _with_parts
from analysis.sentence import Sentence, _is_fresh, _llm_spans
from analysis.span_rows import (
    _basis_changed,
    _is_place_conflict,
    _stored_keys,
    closed_rows,
    judged_rows,
)
from analysis.stream import _NDJSON, _ndjson
from analysis.usage import RequestUsage
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error

logger = logging.getLogger(__name__)


def _new_spans(sentence):
    """저장 열쇠에 없는 새 구간. (새 DB 확정 구간, 새 판별 대상 구간)이다."""
    stored_keys = _stored_keys(sentence.cached)
    s = sentence
    new_closed = [closed for closed in s.closed_spans if s.span_key(closed[0]) not in stored_keys]
    new_spans = [span for span in s.spans if s.span_key(span) not in stored_keys]
    return new_closed, new_spans


def grown_spans(sentence):
    """다시 판정할, 후보가 늘어난 저장 구간. (이 요청의 구간, 저장 행) 목록(원문 순서)이다(#176).

    판별 대상 구간(sentence.spans) 중 저장 행이 있고, 지금 후보에 그 행이 본 적 없는 용법이 있는
    구간이다. 본 용법은 저장된 후보, 고른 용법(미발견 구간이 더한 자기 새 용법), 대안이다. 판별
    규칙·용법 완결로 정해지는 구간은 closed_spans라 들지 않고, 그렇게 정한 저장 행도 뺀다.
    """
    rows = {
        (row.pattern_id, row.start_offset, row.end_offset): row
        for row in sentence.cached.span_matches.filter(decided_by=SpanMatch.DecidedBy.LLM)
    }
    grown = []
    for span in sentence.spans:
        row = rows.get(sentence.span_key(span))
        if row is None:
            continue
        seen = {row.usage_id} | {c["usage_id"] for c in row.candidates or ()}
        seen |= {alt["usage_id"] for alt in row.alternatives or ()}
        if {usage.id for _, usage in span.candidates} - seen:
            grown.append((span, row))
    return grown


def _basis(grown):
    """재판정 잠금 키에 붙일, 다시 판정할 구간의 후보 상태(#176). 없으면 빈 문자열이다."""
    if not grown:
        return ""
    state = sorted((row.pk, [usage.id for _, usage in span.candidates]) for span, row in grown)
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()[:16]


def _candidates_changed(grown):
    """다시 판정한 구간의 지금 후보가 판정할 때와 다른가(#176). 다르면 다음 조회가 다시 판정한다."""
    found = patterns._with_candidates(
        GrammarPattern.objects.filter(pk__in={span.pattern.pk for span, _ in grown})
    ).in_bulk()
    return any(
        span.pattern.pk not in found
        or [u.id for u in patterns.candidate_usages(found[span.pattern.pk])]
        != [u.id for _, u in span.candidates]
        for span, _ in grown
    )


def _still_stored(analysis, grown):
    """다시 판정한 저장 행이 판정할 때 읽은 그대로 남아 있는가(#176)."""
    current = dict(
        analysis.span_matches.filter(pk__in=[row.pk for _, row in grown]).values_list(
            "pk", "candidates"
        )
    )
    return all(row.pk in current and current[row.pk] == row.candidates for _, row in grown)


def _lock_holder(key):
    try:
        return jobs.lock_holder(key)
    except redis.RedisError:
        logger.warning("재판정 잠금을 읽지 못함")
        return None


def rematch(presenter, user, grown):
    """패턴 세트 버전이 오른 캐시 분석을 이 요청의 원문으로 다시 매칭한다(#41). 후보가 늘어난
    저장 구간(grown_spans)이 있으면 그 구간도 함께 다시 판정한다(#176).

    그 밖의 저장 구간은 지우거나 바꾸지 않고, 저장 열쇠에 없는 새 구간만 더한다. 승인된 용법 완결
    패턴의 구간은 LLM 없이 정한다. 일괄 재처리는 하지 않아 다시 조회한 문장에만 비용이 든다.
    """
    s = presenter.sentence
    new_closed, new_spans = _new_spans(s)
    judging = bool(new_spans or grown)
    may_judge = judging and not limits.over_limit(user)
    key = jobs.rematch_lock_key(s.sentence_hash, s.matcher_version, _basis(grown))
    # 하루 한도를 넘은 사용자도 다른 요청이 이미 잡은 재판정은 기다린다(#28).
    if may_judge or (judging and _lock_holder(key)):
        return StreamingHttpResponse(
            rematch_stream(presenter, user, new_closed, new_spans, grown, may_judge),
            content_type=_NDJSON,
        )
    # LLM이 필요 없으면 한 번에 보낸다. 재판정이 필요한데 하루 한도를 넘었으면 저장하지 않고
    # 대체 응답을 보내, 다음 조회가 다시 시도한다(#28).
    event = None if judging else save_rematch(s, presenter.analysis_event, new_closed)
    RequestUsage.start(UsageLog.Path.DB, user, s.cached.pk, success=event is not None)
    event = event or rematch_fallback(presenter, new_closed)
    events = [
        {"type": "translation", "translation_ko": event["translation_ko"], "ruby": presenter.ruby},
        event,
    ]
    user_sentences.record(user, presenter.original, s.cached.pk, event["words"])
    return HttpResponse("".join(map(_ndjson, events)), content_type=_NDJSON)


def rematch_grammar(presenter, analysis, new_closed, excluded=()):
    """저장 구간(조회 규칙 적용)에, 아직 저장되지 않은 새 DB 확정 구간을 더한 문법.
    _grammar_entries와 같은 (항목, show_parts) 목록(원문 순서)이다. excluded는 뺄 저장 행 ID다.

    확정 구간의 패턴·용법 상태는 DB에서 다시 읽어 반려됐으면 뺀다. 매칭할 때 읽은 상태라
    그사이 반려됐을 수 있다.
    """
    s = presenter.sentence
    grammar = presenter.grammar_entries(analysis, excluded)
    stored_keys = _stored_keys(analysis)
    usages = GrammarUsage.objects.select_related("pattern").in_bulk(
        [usage.id for _, _, usage, _ in new_closed]
    )
    matched = GrammarPattern.objects.select_related("variant_of").in_bulk(
        [span.pattern.id for span, *_ in new_closed]
    )
    for span, _, usage, _ in new_closed:
        current = usages.get(usage.id)
        if s.span_key(span) in stored_keys or current is None:
            continue
        start, end = s.key_span(span.start_token, span.end_token)
        pattern = matched[span.pattern.id]
        item = presenter.grammar_item(pattern, current, start, end)
        if item is not None:
            grammar.append((item, pattern.show_parts))
    return sorted(grammar, key=lambda entry: (entry[0]["start"], entry[0]["end"]))


def rematch_fallback(presenter, new_closed):
    """저장된 결과로 만든 analysis 이벤트. 재판정 작업이 저장했으면 그 결과가, 저장하지 못했으면
    대체 응답이 된다.

    분석 행을 잠가 행과 구간을 한 시점에서 다시 읽는다(구간을 쓰는 모든 경로가 분석 행을
    잠근 뒤 커밋한다). 시작 때 읽은 행은 쓰지 않는다. 오래 기다린 뒤라 옛 번역과 새 구간이
    섞일 수 있다. 그 행이 그대로(fresh이고 세대 번호가 같음)일 때만 새 DB 확정 구간을 더한다.
    """
    s = presenter.sentence
    with transaction.atomic():
        row = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=s.cached.pk)
        event = presenter.analysis_event(row)
        if _is_fresh(row) and row.generation == s.started_generation:
            event["grammar"] = _with_parts(rematch_grammar(presenter, row, new_closed))
        return event


def save_rematch(
    sentence, event_of, new_closed, span_list=(), answers=(), alternatives=None, grown=()
):
    """다시 매칭해 새로 생긴 구간을 캐시 분석에 더하고, 잠근 분석 행으로 event_of의 결과를
    돌려준다. span_list의 구간 중 grown(후보가 늘어난 저장 구간)에 든 것은 그 저장 행을 새
    판정으로 바꾼다(#176).

    새 용법 → (자격을 얻었으면) 패턴 세트 버전 → 분석 행 순서로 잠근다. 분석 행을 잠근 뒤
    fresh인지, 세대 번호가 같은지, (버전이 올랐으면) 아직 이 버전으로 다시 매칭하지 않았는지, 새
    열쇠가 아직 저장되지 않았는지, 바꿀 저장 행이 그대로인지 다시 본다. 바꿀 구간의 후보가 판정할
    때와 다르면 저장하지 않는다. 하나라도 어긋나면 모두 되돌리고 None이다.
    """
    cached = sentence.cached
    rematching = cached.matcher_version < sentence.matcher_version
    with transaction.atomic():
        patterns.lock_links()
        # 이 저장이 미발견 구간에 더할 새 용법까지 후보로 세지 않게 용법을 더하기 전에 본다.
        if grown and _candidates_changed(grown):
            transaction.set_rollback(True)
            return None
        rows, activated = judged_rows(
            sentence, cached, list(span_list), list(answers), alternatives
        )
        rows = closed_rows(sentence, cached, new_closed) + rows
        if activated:
            patterns.raise_pattern_set_version()
        locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=cached.pk)
        replaced = {(row.pattern_id, row.start_offset, row.end_offset) for _, row in grown}
        new_keys = {(row.pattern_id, row.start_offset, row.end_offset) for row in rows} - replaced
        if (
            not _is_fresh(locked)
            or locked.generation != sentence.started_generation
            or (rematching and locked.matcher_version >= sentence.matcher_version)
            or new_keys & _stored_keys(locked)
            or not _still_stored(locked, grown)
            or _basis_changed(rows, sentence.rules)
        ):
            transaction.set_rollback(True)
            return None
        try:
            with transaction.atomic():
                SpanMatch.objects.filter(pk__in=[row.pk for _, row in grown]).delete()
                SpanMatch.objects.bulk_create(rows)
        except IntegrityError as e:
            if not _is_place_conflict(e):
                raise
            transaction.set_rollback(True)
            return None
        if rematching:
            locked.matcher_version = sentence.matcher_version
            locked.save(update_fields=["matcher_version", "updated_at"])
        return event_of(locked)


def rematch_decided(sentence, new_closed, grown=()):
    """재판정에 알릴, 해석이 정해진 구간(이 요청 형태소의 토큰 범위).

    조회 규칙을 거친 저장 결정 구간, 해석 갈림의 주 용법, 새 DB 확정 구간이다. 다시 판정하는
    구간(grown)은 뺀다. 숫자 표기가 달라 형태소 경계가 다른 원문이면 저장 위치를 토큰으로
    되돌리지 못할 수 있고, 그 구간은 뺀다.
    """
    starts, ends = {}, {}
    for token in range(len(sentence.morphs)):
        start, end = sentence.key_span(token, token)
        starts.setdefault(start, token)
        ends[end] = token
    decided = []
    stored = (
        sentence.cached.span_matches.filter(
            state__in=(SpanMatch.State.DECIDED, SpanMatch.State.DIVERGENT)
        )
        .exclude(pk__in=[row.pk for _, row in grown])
        .select_related("pattern__variant_of", "usage__pattern")
        .order_by("start_offset", "end_offset", "id")
    )
    for span in stored:
        first, last = starts.get(span.start_offset), ends.get(span.end_offset)
        if first is None or last is None or first > last:
            continue
        if _review_status(span.pattern, span.usage) is not None:
            decided.append({"start_token_id": first, "end_token_id": last, "name": span.usage.name})
    decided += [
        {"start_token_id": span.start_token, "end_token_id": span.end_token, "name": usage.name}
        for span, _, usage, _ in new_closed
    ]
    return decided


def judge_rematched(sentence, event_of, new_closed, new_spans, usage, grown=()):
    """새 판별 대상 구간과 후보가 늘어난 저장 구간(grown, #176)을 재판정 한 번으로 정하고
    저장한다. 저장하지 못했으면 None.

    첫 분석의 판정 규칙(해석 갈림 대안 포함)으로 검증한다. 이 호출이 마지막이라 다시 묻지
    않는다. 번역은 저장된 것으로 "번역과 같은 해석"을 고르게 하고 바꾸지 않는다. LLM 호출과
    검증은 저장 트랜잭션 밖에서 한다.
    """
    cached = sentence.cached
    span_list = sorted(
        [*new_spans, *(span for span, _ in grown)],
        key=lambda span: (span.start_token, span.end_token),
    )
    client = llm.get_client(usage.record_llm)
    result = client.rematch_judge(
        sentence.key_text,
        sentence.tokens,
        cached.translation_ko,
        rematch_decided(sentence, new_closed, grown),
        _llm_spans(span_list),
    )
    if not isinstance(result, dict):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 재판정")
    checked = _validate_recheck_answers(
        result.get("spans"), span_list, [FIRST_VERDICTS] * len(span_list), sentence.numbers
    )
    if checked is None:
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 재판정")
    answers, alternatives = checked
    # 대안 번역이 저장 번역과 같으면 갈린 해석이 아니다.
    if any(
        alt.strip() == cached.translation_ko.strip()
        for alts in alternatives.values()
        for _, alt in alts
    ):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 대안 번역")
    validated = {"new_patterns": [], "span_list": span_list, "spans": answers}
    reject_quotes(validated, sentence)
    new_keys = {sentence.span_key(span) for span in new_spans}

    def discarded():
        return bool(new_keys & _stored_keys(cached)) or not _still_stored(cached, grown)

    _check_examples(
        validated,
        client,
        sentence.key_text,
        sentence.content_tokens,
        sentence.key_span,
        discarded,
    )
    return save_rematch(sentence, event_of, new_closed, span_list, answers, alternatives, grown)


def rematch_early(presenter, new_closed, new_spans, grown=()):
    """재판정을 기다리기 전에 보낼 이벤트. 저장 구간과 새 DB 확정 구간, 판별 대상(확인 중) →
    저장 번역 순서다. 다시 판정하는 저장 구간(grown)은 확정 목록에서 빼고 확인 중에 넣는다(#176).
    먼저 오는 grammar 이벤트는 평평하게 둔다. 하위 박스는 analysis에만 있다(#65).
    """
    s = presenter.sentence
    excluded = [row.pk for _, row in grown]
    return [
        {
            "type": "grammar",
            "grammar": [
                item for item, _ in rematch_grammar(presenter, s.cached, new_closed, excluded)
            ],
            "checking": presenter.checking([*new_spans, *(span for span, _ in grown)]),
        },
        presenter.translation_event(s.cached.translation_ko),
    ]


def start_judge(sentence, usage, may_judge, grown=()):
    """재판정 잠금을 잡았으면 작업을 큐에 넣는다. 기다릴 시도(잠금 값)를 돌려주고, 기다릴 작업이
    없으면(큐 넣기 실패 포함) None이다.

    못 잡았으면 잡은 시도를 기다린다. 그사이 풀렸으면 다시 잡는다. 하루 한도를 넘은 요청
    (may_judge가 거짓)은 잡지 않고 기다리기만 한다.
    """
    basis = _basis(grown)
    key = jobs.rematch_lock_key(sentence.sentence_hash, sentence.matcher_version, basis)
    try:
        while True:
            token = uuid.uuid4().hex
            if may_judge and jobs.take_lock(key, token):
                break
            holder = jobs.lock_holder(key)
            if holder is not None or not may_judge:
                return holder
    except redis.RedisError:
        logger.warning("재판정 잠금을 잡지 못함: analysis_id=%s", sentence.cached.pk)
        return None
    try:
        jobs.enqueue_rematch(
            sentence.cached.pk, sentence.text, usage.id, sentence.matcher_version, token, basis
        )
    except BusinessError as e:
        log_business_error(e)
        # 풀지 못해도 만료되면 다음 조회가 다시 잡는다.
        with contextlib.suppress(redis.RedisError):
            jobs.release_lock(key, token)
        return None
    return token


def rematch_result(presenter, user, new_closed):
    event = rematch_fallback(presenter, new_closed)
    user_sentences.record(user, presenter.original, presenter.sentence.cached.pk, event["words"])
    return event


async def rematch_stream(presenter, user, new_closed, new_spans, grown, may_judge):
    """판별 대상 새 구간이나 후보가 늘어난 저장 구간(#176)이 있는 재매칭의 이벤트.
    rematch_early → analysis 순서다.

    rematch_early를 보내고 작업 소식을 구독한 뒤 재판정 잠금을 잡거나 잡은 시도에 붙고, 그
    시도의 소식만 받는다. analysis는 성공·실패와 관계없이 저장된 결과로 만든다. 실패 소식,
    대기 상한, 큐 넣기 실패에도 error 대신 이 대체 응답을 보내고, 다음 조회가 다시 시도한다.
    """
    s = presenter.sentence
    # 구독과 상관없는 이벤트라 먼저 보낸다. 구독에 실패해도 루비가 담긴 번역은 간다(PR #163 리뷰).
    for event in await sync_to_async(rematch_early)(presenter, new_closed, new_spans, grown):
        yield _ndjson(event)
    saved = False
    try:
        async with jobs.listen(s.sentence_hash) as pubsub:
            usage = await sync_to_async(RequestUsage.start)(UsageLog.Path.LLM, user, s.cached.pk)
            attempt = await sync_to_async(start_judge)(s, usage, may_judge, grown)
            if attempt is not None:
                async for message in jobs.messages(pubsub, stream.WAIT_SECONDS):
                    if message.get("attempt") == attempt:
                        saved = message["type"] == "done"
                        break
                else:
                    logger.warning("재판정 작업 대기 시간 초과: analysis_id=%s", s.cached.pk)
    except redis.RedisError:
        # 소식을 받지 못해도 저장된 결과는 DB에 있다(PR #163 리뷰).
        logger.warning("재판정 작업 소식을 받지 못함: analysis_id=%s", s.cached.pk)
    if saved:
        await sync_to_async(usage.succeed)()
    yield _ndjson(await sync_to_async(rematch_result)(presenter, user, new_closed))


def run_rematch(analysis_id, text, usage_id, version, token, basis=""):
    """작업자가 실행하는 재판정 작업(analysis.jobs). text는 분석 텍스트, version·token·basis는
    요청이 잡은 재판정 잠금이다.

    잠금이 자기 것이 아니면 LLM을 부르지 않고 끝낸다. 끝나면 성공·실패와 관계없이 자기 잠금만
    풀고 done 또는 failed를 알린다. 잠금을 먼저 풀어, 실패 소식을 받은 뒤의 조회가 다시 잡게 한다.
    """
    sentence_hash = SentenceAnalysis.objects.values_list("sentence_hash", flat=True).get(
        pk=analysis_id
    )
    key = jobs.rematch_lock_key(sentence_hash, version, basis)
    if jobs.lock_holder(key) != token:
        return
    saved = False
    try:
        saved = _judge(Sentence(text), analysis_id, usage_id, version, basis)
    finally:
        # 풀지 못해도 만료된다. 기다리는 요청이 대기 상한까지 붙잡히지 않게 소식은 꼭 보낸다.
        with contextlib.suppress(redis.RedisError):
            jobs.release_lock(key, token)
        jobs.publish(sentence_hash, {"type": "done" if saved else "failed", "attempt": token})


def _judge(sentence, analysis_id, usage_id, version, basis):
    """작업자가 다시 매칭해 재판정·저장한다. 저장된 결과가 이 버전 이상이고 다시 판정할 구간이
    없으면 참이다.

    로그에는 원문 없이 목적·분석 ID·오류 코드만 남긴다.
    """
    cached = sentence.cached
    if cached is None or cached.pk != analysis_id:
        # 그사이 stale이 됐다. stale 재분석이 이긴다.
        return False
    grown = grown_spans(sentence)
    if cached.matcher_version >= sentence.matcher_version and not grown:
        # 잠금이 만료된 사이 다른 시도가 먼저 저장했다.
        return True
    if sentence.matcher_version != version or _basis(grown) != basis:
        # 큐에서 기다리는 사이 패턴 세트 버전이나 후보가 바뀌었다. 새 잠금을 잡을 조회에 맡긴다.
        return False
    request = UsageLog.objects.get(pk=usage_id)
    if limits.over_limit(request.user):
        return False
    new_closed, new_spans = _new_spans(sentence)
    try:
        if new_spans or grown:
            usage = RequestUsage(request)
            saved = judge_rematched(sentence, lambda row: row, new_closed, new_spans, usage, grown)
        else:
            saved = save_rematch(sentence, lambda row: row, new_closed)
    except BusinessError as e:
        logger.warning(
            "rematch_judge 실패: analysis_id=%s error=%s", analysis_id, e.error_code.code
        )
        return False
    return saved is not None
