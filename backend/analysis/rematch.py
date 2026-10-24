"""패턴 세트 버전이 오른 캐시 분석의 재매칭(#41).

재판정·저장(save_rematch, judge_rematched)은 Sentence와, 잠근 분석 행으로 결과를 만드는
event_of만 받는다. 요청이 아닌 쪽(#114의 작업자)에서도 부를 수 있게 하기 위해서다.
"""

import logging
from itertools import chain

from django.db import IntegrityError, transaction
from django.http import HttpResponse, StreamingHttpResponse

from analysis import limits, llm, patterns, user_sentences
from analysis.answers import FIRST_VERDICTS, _validate_recheck_answers, reject_quotes
from analysis.examples import _check_examples
from analysis.models import GrammarPattern, GrammarUsage, SentenceAnalysis, SpanMatch, UsageLog
from analysis.presenter import _review_status, _with_parts
from analysis.sentence import _is_fresh, _llm_spans
from analysis.span_rows import (
    _basis_changed,
    _is_place_conflict,
    _stored_keys,
    closed_rows,
    judged_rows,
)
from analysis.stream import _NDJSON, _in_thread, _ndjson
from analysis.usage import RequestUsage
from errors import AnalysisError, BusinessError

logger = logging.getLogger(__name__)


def rematch(presenter, user):
    """패턴 세트 버전이 오른 캐시 분석을 이 요청의 원문으로 다시 매칭한다(#41).

    저장 구간은 지우거나 바꾸지 않고, 저장 열쇠에 없는 새 구간만 더한다. 승인된 용법 완결
    패턴의 구간은 LLM 없이 정한다. 일괄 재처리는 하지 않아 다시 조회한 문장에만 비용이 든다.
    """
    s = presenter.sentence
    stored_keys = _stored_keys(s.cached)
    new_closed = [closed for closed in s.closed_spans if s.span_key(closed[0]) not in stored_keys]
    new_spans = [span for span in s.spans if s.span_key(span) not in stored_keys]
    if new_spans and not limits.over_limit(user):
        # 판정을 기다리는 동안 새 구간은 '확인 중'으로 보인다.
        usage = RequestUsage.start(UsageLog.Path.LLM, user, s.cached.pk)
        events = rematch_and_judge(presenter, user, new_closed, new_spans, usage)
        first = next(events)
        return StreamingHttpResponse(_in_thread(chain([first], events)), content_type=_NDJSON)
    # LLM이 필요 없으면 클라이언트를 만들지 않고 한 번에 보낸다. 재판정이 필요한데 하루 한도를
    # 넘었으면 저장하지 않고 대체 응답을 보내, 다음 조회가 다시 시도한다(#28).
    event = None if new_spans else save_rematch(s, presenter.analysis_event, new_closed)
    RequestUsage.start(UsageLog.Path.DB, user, s.cached.pk, success=event is not None)
    event = event or rematch_fallback(presenter, new_closed)
    events = [
        {"type": "translation", "translation_ko": event["translation_ko"], "ruby": presenter.ruby},
        event,
    ]
    user_sentences.record(user, presenter.original, s.cached.pk)
    return HttpResponse("".join(map(_ndjson, events)), content_type=_NDJSON)


def rematch_grammar(presenter, analysis, new_closed):
    """저장 구간(조회 규칙 적용)에, 아직 저장되지 않은 새 DB 확정 구간을 더한 문법.
    _grammar_entries와 같은 (항목, show_parts) 목록(원문 순서)이다.

    확정 구간의 패턴·용법 상태는 DB에서 다시 읽어 반려됐으면 뺀다. 매칭할 때 읽은 상태라
    그사이 반려됐을 수 있다.
    """
    s = presenter.sentence
    grammar = presenter.grammar_entries(analysis)
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
    """다시 매칭한 결과를 저장하지 못했을 때의 analysis 이벤트.

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


def save_rematch(sentence, event_of, new_closed, span_list=(), answers=(), alternatives=None):
    """다시 매칭해 새로 생긴 구간을 캐시 분석에 더하고, 잠근 분석 행으로 event_of의 결과를
    돌려준다.

    새 용법 → (자격을 얻었으면) 패턴 세트 버전 → 분석 행 순서로 잠근다. 분석 행을 잠근 뒤
    fresh인지, 세대 번호가 같은지, 아직 이 버전으로 다시 매칭하지 않았는지, 새 열쇠가 아직
    저장되지 않았는지 다시 본다. 하나라도 어긋나면 모두 되돌리고 None이다.
    """
    cached = sentence.cached
    with transaction.atomic():
        patterns.lock_links()
        rows, activated = judged_rows(
            sentence, cached, list(span_list), list(answers), alternatives
        )
        rows = closed_rows(sentence, cached, new_closed) + rows
        if activated:
            patterns.raise_pattern_set_version()
        locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=cached.pk)
        new_keys = {(row.pattern_id, row.start_offset, row.end_offset) for row in rows}
        if (
            not _is_fresh(locked)
            or locked.generation != sentence.started_generation
            or locked.matcher_version >= sentence.matcher_version
            or new_keys & _stored_keys(locked)
            or _basis_changed(rows, sentence.rules)
        ):
            transaction.set_rollback(True)
            return None
        try:
            with transaction.atomic():
                SpanMatch.objects.bulk_create(rows)
        except IntegrityError as e:
            if not _is_place_conflict(e):
                raise
            transaction.set_rollback(True)
            return None
        locked.matcher_version = sentence.matcher_version
        locked.save(update_fields=["matcher_version", "updated_at"])
        return event_of(locked)


def rematch_decided(sentence, new_closed):
    """재판정에 알릴, 해석이 정해진 구간(이 요청 형태소의 토큰 범위).

    조회 규칙을 거친 저장 결정 구간, 해석 갈림의 주 용법, 새 DB 확정 구간이다. 숫자 표기가
    달라 형태소 경계가 다른 원문이면 저장 위치를 토큰으로 되돌리지 못할 수 있고, 그 구간은
    뺀다.
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


def judge_rematched(sentence, event_of, new_closed, new_spans, usage):
    """새 판별 대상 구간을 재판정 한 번으로 정하고 저장한다. 저장하지 못했으면 None.

    첫 분석의 판정 규칙(해석 갈림 대안 포함)으로 검증한다. 이 호출이 마지막이라 다시 묻지
    않는다. 번역은 저장된 것으로 "번역과 같은 해석"을 고르게 하고 바꾸지 않는다. LLM 호출과
    검증은 저장 트랜잭션 밖에서 한다.
    """
    cached = sentence.cached
    client = llm.get_client(usage.record_llm)
    result = client.rematch_judge(
        sentence.key_text,
        sentence.tokens,
        cached.translation_ko,
        rematch_decided(sentence, new_closed),
        _llm_spans(new_spans),
    )
    if not isinstance(result, dict):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 재판정")
    checked = _validate_recheck_answers(
        result.get("spans"), new_spans, [FIRST_VERDICTS] * len(new_spans), sentence.numbers
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
    validated = {"new_patterns": [], "span_list": new_spans, "spans": answers}
    reject_quotes(validated, sentence)
    new_keys = {sentence.span_key(span) for span in new_spans}

    def discarded():
        return bool(new_keys & _stored_keys(cached))

    _check_examples(
        validated,
        client,
        sentence.key_text,
        sentence.content_tokens,
        sentence.key_span,
        discarded,
    )
    return save_rematch(sentence, event_of, new_closed, new_spans, answers, alternatives)


def rematch_and_judge(presenter, user, new_closed, new_spans, usage):
    """판별 대상 새 구간이 있는 재매칭의 이벤트. 저장 구간과 새 DB 확정 구간, 판별 대상(확인
    중) → 저장 번역 → 재판정·저장 → analysis 순서다.

    재판정이나 저장이 실패하면 아무것도 저장하지 않고 error 대신 대체 응답을 보낸다. 다음
    조회가 다시 시도한다. 로그에는 원문 없이 목적·분석 ID·오류 코드만 남긴다.
    """
    s = presenter.sentence
    # 먼저 오는 grammar 이벤트는 평평하게 둔다. 하위 박스는 analysis에만 있다(#65).
    yield {
        "type": "grammar",
        "grammar": [item for item, _ in rematch_grammar(presenter, s.cached, new_closed)],
        "checking": presenter.checking(new_spans),
    }
    yield presenter.translation_event(s.cached.translation_ko)
    try:
        event = judge_rematched(s, presenter.analysis_event, new_closed, new_spans, usage)
        if event is None:
            raise BusinessError(AnalysisError.FAILED, "재판정 저장 전 분석이 바뀜")
        usage.succeed()
    except BusinessError as e:
        logger.warning(
            "rematch_judge 실패: analysis_id=%s error=%s", s.cached.pk, e.error_code.code
        )
        event = rematch_fallback(presenter, new_closed)
    user_sentences.record(user, presenter.original, s.cached.pk)
    yield event
