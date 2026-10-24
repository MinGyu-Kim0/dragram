"""원문 기준 응답 이벤트."""

from analysis import words
from analysis.models import (
    GrammarUsage,
    ReviewStatus,
    SpanMatch,
    WordSense,
)
from analysis.positions import to_analysis, to_original
from analysis.sentence import _pattern_statuses

# 화면에 보이는 구간 판정
_SHOWN_STATES = (
    SpanMatch.State.DECIDED,
    SpanMatch.State.DIVERGENT,
    SpanMatch.State.UNRESOLVED,
)


def _grammar_response(analysis, offsets, origins, utf16, restore):
    """analysis 이벤트의 문법: 저장 구간을 보이고, 구성 문법은 바깥 항목의 parts에 넣는다(#65)."""
    return _with_parts(_grammar_entries(analysis, offsets, origins, utf16, restore))


def _grammar_entries(analysis, offsets, origins, utf16, restore):
    """용법이 정해진 구간, 해석 갈림, 미확정 구간을 이 요청 원문의 UTF-16 위치로 보인다.
    (항목, 매칭된 패턴의 show_parts) 목록(원문 순서)이다.

    같은 분석을 표기가 다른 원문(앞 공백, 괄호, 숫자 자릿수 등)이 함께 쓰므로, 요청마다
    그 원문 기준으로 다시 계산한다. 검수 상태는 저장하지 않고 볼 때마다 정한다(ADR 0003):
    고른 용법, 그 용법이 속한 패턴, 실제로 매칭된 패턴 중 하나라도 반려됐으면 빼고, 미검수면
    'AI 생성·미검수'다. 해석 갈림의 대안도 하나씩 같게 보고, 반려된 대안만 뺀다(주 용법 쪽이
    반려면 구간째 뺀다). 미확정은 매칭된 패턴만 본다.
    """
    spans = list(
        analysis.span_matches.filter(state__in=_SHOWN_STATES)
        .select_related("pattern__variant_of", "usage__pattern")
        .order_by("start_offset", "end_offset", "id")
    )
    alternative_usages = GrammarUsage.objects.select_related("pattern").in_bulk(
        [alt["usage_id"] for span in spans for alt in span.alternatives or []]
    )
    entries = []
    for span in spans:
        if span.state == SpanMatch.State.UNRESOLVED:
            item = _unresolved_item(span, offsets, origins, utf16)
        else:
            item = _grammar_item(
                span.pattern,
                span.usage,
                span.start_offset,
                span.end_offset,
                offsets,
                origins,
                utf16,
                span.state,
            )
        if item is None:
            continue
        if span.state == SpanMatch.State.DIVERGENT:
            item["alternatives"] = []
            for alt in span.alternatives:
                usage = alternative_usages.get(alt["usage_id"])
                review_status = _review_status(span.pattern, usage) if usage else None
                if review_status is not None:
                    item["alternatives"].append(
                        {
                            "name": usage.name,
                            "translation_ko": restore(alt["translation_ko"]),
                            "review_status": review_status,
                        }
                    )
        entries.append((item, span.pattern.show_parts))
    return entries


# 구성 문법의 바깥 카드가 될 수 있는 판정 상태(#65). 미확정은 설명 없는 카드 뒤로 설명을 숨기지
# 않도록 바깥이 되지 않는다.
_OUTER_STATES = (SpanMatch.State.DECIDED, SpanMatch.State.DIVERGENT)


def _with_parts(entries):
    """(항목, 매칭된 패턴의 show_parts) 목록(원문 순서)에서 구성 문법을 바깥 항목의 parts로 옮긴다.

    구성 문법은 범위가 다르고 완전히 들어가는 결정·해석 갈림 항목 가운데 가장 작은 것(크기가
    같으면 원문 순서로 앞선 것)에 붙는다. 하위 박스는 한 단이라, 그 바깥이 다시 구성 문법이면 가장
    바깥 항목 아래로 놓는다. 위로 이어지는 바깥 가운데 하나라도 show_parts가 꺼져 있으면 응답에서
    뺀다(#65).
    """

    def contains(outer, inner):
        return (outer["start"], outer["end"]) != (inner["start"], inner["end"]) and (
            outer["start"] <= inner["start"] and inner["end"] <= outer["end"]
        )

    items = [item for item, _ in entries]
    parents = [
        min(
            (
                i
                for i, outer in enumerate(items)
                if outer["state"] in _OUTER_STATES and contains(outer, item)
            ),
            key=lambda i: items[i]["end"] - items[i]["start"],
            default=None,
        )
        for item in items
    ]
    grammar = []
    for i, item in enumerate(items):
        top, shown = i, True
        while parents[top] is not None:
            top = parents[top]
            shown = shown and entries[top][1]
        if top == i:
            grammar.append(item)
        elif shown:
            items[top].setdefault("parts", []).append(item)
    return grammar


def _grammar_item(
    pattern,
    usage,
    start_offset,
    end_offset,
    offsets,
    origins,
    utf16,
    state=SpanMatch.State.DECIDED,
):
    """용법이 정해진 구간 하나를 응답 항목으로 만든다. 반려됐으면 None(ADR 0003)."""
    review_status = _review_status(pattern, usage)
    if review_status is None:
        return None
    start, end = to_original(origins, utf16, *to_analysis(offsets, start_offset, end_offset))
    return {
        "start": start,
        "end": end,
        "state": state,
        "name": usage.name,
        "explanation_ko": usage.explanation_ko,
        "review_status": review_status,
        **_register_fields(pattern),
    }


def _register_fields(pattern):
    """회화체 표시 칸: 매칭된 패턴의 register와, 연결된 원형 패턴 이름(없으면 null, #63)."""
    base = pattern.variant_of
    return {"register": pattern.register, "variant_of": base.name if base else None}


def _unresolved_item(span, offsets, origins, utf16):
    """미확정 구간의 응답 항목. 이름은 매칭된 패턴의 것이고 설명은 없다. 매칭된 패턴이나 연결된
    원형이 반려됐으면 None, 하나라도 미검수면 pending이다.
    """
    statuses = _pattern_statuses(span.pattern)
    if ReviewStatus.REJECTED in statuses:
        return None
    start, end = to_original(
        origins, utf16, *to_analysis(offsets, span.start_offset, span.end_offset)
    )
    return {
        "start": start,
        "end": end,
        "state": SpanMatch.State.UNRESOLVED,
        "name": span.pattern.name,
        "explanation_ko": None,
        "review_status": "pending" if ReviewStatus.PENDING in statuses else "approved",
        **_register_fields(span.pattern),
    }


def _review_status(pattern, usage):
    """화면에 보일 검수 상태(ADR 0003). 고른 용법, 그 용법이 속한 패턴, 실제로 매칭된 패턴,
    매칭된 패턴이 연결된 원형 중 하나라도 반려됐으면 None(보이지 않음), 미검수면 pending이다.
    용법이 매칭된 패턴이나 그 원형 소속이 아니면(연결 해제 뒤 재분석 전) 역시 None이다(#63).
    용법이 없어도 None이다. 저장을 되돌릴 결과로 응답하는 사이 그 용법이 다른 용법으로 합쳐져
    지워진 경우다(#64).
    """
    if usage is None or usage.pattern_id not in {pattern.id, pattern.variant_of_id}:
        return None
    statuses = {usage.status, usage.pattern.status, *_pattern_statuses(pattern)}
    if ReviewStatus.REJECTED in statuses:
        return None
    return "pending" if ReviewStatus.PENDING in statuses else "approved"


def _words_response(word_spans, text, token_at, offsets, origins, utf16):
    """저장된 단어 위치·뜻을 이 요청 원문의 UTF-16 위치로 보인다(원문 순서).

    뜻은 볼 때마다 DB에서 읽고, 지워졌거나 반려된 뜻의 단어는 뺀다. 읽기는 이 요청의 토큰
    (token_at: 키 텍스트 구간 → 형태소)으로 표기에 맞춰 고른다.
    """
    senses = WordSense.objects.select_related("word").in_bulk(
        {span["sense_id"] for span in word_spans}
    )
    items = []
    for span in sorted(word_spans, key=lambda span: (span["start"], span["end"])):
        sense = senses.get(span["sense_id"])
        if sense is None or sense.sense_status == ReviewStatus.REJECTED:
            continue
        reading = words.reading_for(sense, text, token_at.get((span["start"], span["end"])))
        start, end = to_original(origins, utf16, *to_analysis(offsets, span["start"], span["end"]))
        items.append(words.response_item(start, end, sense.word, reading, sense))
    return items


def _ruby_response(pieces, origins, utf16):
    """분석 텍스트 기준 루비 조각을 이 요청 원문의 UTF-16 위치로 바꾼다."""
    ruby = []
    for start, end, reading in pieces:
        start, end = to_original(origins, utf16, start, end)
        ruby.append({"start": start, "end": end, "reading": reading})
    return ruby
