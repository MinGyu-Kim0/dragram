"""원문 기준 응답 이벤트."""

from analysis import words
from analysis.models import (
    GrammarUsage,
    ReviewStatus,
    SpanMatch,
    WordSense,
)
from analysis.positions import to_analysis, to_original, utf16_offsets
from analysis.ruby import ruby_pieces
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
                            "korean_equivalent": usage.korean_equivalent,
                            "korean_equivalent_review_status": usage.korean_equivalent_status,
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
        "korean_equivalent": usage.korean_equivalent,
        "korean_equivalent_review_status": usage.korean_equivalent_status,
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
        "korean_equivalent": None,
        "korean_equivalent_review_status": None,
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


def _words_response(word_spans, text, token_at, offsets, origins, utf16, before_save=False):
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
        items.append(words.response_item(start, end, sense.word, reading, sense, before_save))
    return items


def _ruby_response(pieces, origins, utf16):
    """분석 텍스트 기준 루비 조각을 이 요청 원문의 UTF-16 위치로 바꾼다."""
    ruby = []
    for start, end, reading in pieces:
        start, end = to_original(origins, utf16, start, end)
        ruby.append({"start": start, "end": end, "reading": reading})
    return ruby


class Presenter:
    """한 요청의 원문(original) 기준 이벤트. origins는 분석 텍스트 글자마다의 원문 구간이다.

    같은 분석을 표기가 다른 원문이 함께 쓰므로, 위치·숫자는 요청마다 그 원문 기준으로 계산한다.
    """

    def __init__(self, sentence, original, origins):
        self.sentence = sentence
        self.original = original
        self.origins = origins
        self.utf16 = utf16_offsets(original)
        # 루비는 SudachiPy 읽기라 LLM·캐시와 상관없이 요청마다 이 원문 기준으로 계산한다.
        self.ruby = _ruby_response(ruby_pieces(sentence.text, sentence.morphs), origins, self.utf16)

    def translation_event(self, translation):
        return {
            "type": "translation",
            "translation_ko": self.sentence.restore(translation),
            "ruby": self.ruby,
        }

    def analysis_event(self, saved):
        # 동시에 저장된 다른 요청의 결과를 쓸 수 있어, 문법·단어와 짝인 번역을 함께 싣는다.
        s = self.sentence
        return {
            "type": "analysis",
            "translation_ko": s.restore(saved.translation_ko),
            "grammar": _grammar_response(saved, s.offsets, self.origins, self.utf16, s.restore),
            "words": _words_response(
                saved.word_spans, s.text, s.token_at, s.offsets, self.origins, self.utf16
            ),
        }

    def judged_event(self, spans, word_spans):
        """첫 LLM 응답이 판정한 문법과 고른 뜻(저장 전, #97). spans·word_spans는 작업자 소식이다.

        용법을 고른 구간은 그 용법의 카드가 되고, 해당 없음은 확인 중에서 빠진다. 해석 갈림·미확정·
        미발견은 다시 묻기나 저장을 기다리므로 확인 중으로 남는다. 새 구문은 저장 전에는 패턴이
        없어 analysis에서 보인다. 구간은 (패턴, 토큰 위치)로 이 요청의 후보 구간과 맞춘다.
        """
        s = self.sentence
        judged = {(j["pattern_id"], j["start_token"], j["end_token"]): j for j in spans}
        grammar, checking = self.closed_grammar(), []
        for span in s.spans:
            answer = judged.get((span.pattern.id, span.start_token, span.end_token))
            state = answer["state"] if answer else None
            if state == SpanMatch.State.DECIDED:
                usage = next((u for _, u in span.candidates if u.id == answer["usage_id"]), None)
                item = usage and self.grammar_item(
                    span.pattern, usage, *s.key_span(span.start_token, span.end_token)
                )
                if item:
                    grammar.append(item)
            elif state != SpanMatch.State.NOT_APPLICABLE:
                checking.append(span)
        return {
            "type": "judged",
            "grammar": sorted(grammar, key=lambda item: (item["start"], item["end"])),
            "checking": self.checking(checking),
            "words": _words_response(
                word_spans, s.text, s.token_at, s.offsets, self.origins, self.utf16, True
            ),
        }

    def grammar_entries(self, analysis):
        """저장 구간의 (항목, show_parts) 목록(원문 순서, _grammar_entries)."""
        s = self.sentence
        return _grammar_entries(analysis, s.offsets, self.origins, self.utf16, s.restore)

    def grammar_item(self, pattern, usage, start_offset, end_offset):
        """키 텍스트 구간 하나의 응답 항목(_grammar_item). 반려됐으면 None."""
        return _grammar_item(
            pattern,
            usage,
            start_offset,
            end_offset,
            self.sentence.offsets,
            self.origins,
            self.utf16,
        )

    def closed_grammar(self):
        """LLM 없이 확정한 구간의 응답 항목(원문 순서)."""
        s = self.sentence
        grammar = []
        for span, _, usage, _ in sorted(
            s.closed_spans, key=lambda c: (c[0].start_token, c[0].end_token)
        ):
            start, end = s.key_span(span.start_token, span.end_token)
            grammar.append(self.grammar_item(span.pattern, usage, start, end))
        return grammar

    def checking(self, span_list):
        """판별 대상 구간의 원문 위치와 후보 용법의 이름·검수 상태(원문 순서). 후보 이름도 LLM이
        만든 지식이라 미검수면 미검수로 보인다(불변식). 반려된 용법은 후보에 없다.
        """
        s = self.sentence
        items = []
        for span in sorted(span_list, key=lambda span: (span.start_token, span.end_token)):
            key_start, key_end = s.key_span(span.start_token, span.end_token)
            start, end = to_original(
                self.origins, self.utf16, *to_analysis(s.offsets, key_start, key_end)
            )
            candidates = [
                {"name": usage.name, "review_status": _review_status(span.pattern, usage)}
                for _, usage in span.candidates
            ]
            items.append({"start": start, "end": end, "candidates": candidates})
        return items

    def sentence_words(self):
        """LLM 응답 전에 보낼 단어(원문 순서). 뜻이 여럿인 단어는 표제·읽기·태그만 보낸다(뜻은
        None). 여러 항목이 걸렸으면(開く あく/ひらく) 고르기 전이라 읽기는 모두 잇고(・) 태그는
        항목들에 공통인 것만 보인다.
        """
        morphs = self.sentence.morphs
        items = []
        for token, cands in self.sentence.found.items():
            start, end = to_original(
                self.origins, self.utf16, morphs[token].begin, morphs[token].end
            )
            if len(cands) == 1:
                [only] = cands
                items.append(
                    words.response_item(
                        start, end, only.sense.word, only.reading, only.sense, before_save=True
                    )
                )
                continue
            item = words.response_item(start, end, cands[0].sense.word, cands[0].reading, None)
            item["reading"] = "・".join(dict.fromkeys(c.reading for c in cands))
            item["tags"] = sorted(
                set.intersection(*(set(words.word_tags(c.sense.word)) for c in cands))
            )
            items.append(item)
        return items

    def early_events(self):
        """LLM을 기다리기 전에 DB만으로 보낼 이벤트.

        stale 행의 옛 결과는 다시 분석하는 동안 '재분석 중'으로 보이도록 먼저 보낸다(#60). 저장된
        결과를 그대로 내보내지 않고 analysis 이벤트와 같은 경로로 만들어, 반려된 구간은 빠지고 검수
        상태는 지금 지식 상태로 다시 계산된다. 이어서 확정 구간과 판별 대상 구간(화면의 확인 중),
        사전에서 찾은 단어를 보낸다(#39, #44, #96).
        """
        s = self.sentence
        events = []
        if s.existing is not None and s.existing.word_spans is not None:
            events.append(
                {**self.analysis_event(s.existing), "type": "previous", "ruby": self.ruby}
            )
        early_words = self.sentence_words()
        if s.closed_spans or s.spans or early_words:
            events.append(
                {
                    "type": "grammar",
                    "grammar": self.closed_grammar(),
                    "checking": self.checking(s.spans),
                    "words": early_words,
                }
            )
        return events
