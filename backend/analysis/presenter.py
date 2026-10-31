"""원문 기준 응답 이벤트."""

from django.db import transaction

from analysis import patterns, words
from analysis.korean_reading import korean_reading, place_reading
from analysis.models import (
    GrammarUsage,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
    WordSense,
)
from analysis.normalize import has_only_known_placeholders, settled_prefix
from analysis.positions import to_analysis, to_original, utf16_offsets
from analysis.ruby import ruby_pieces
from analysis.sentence import _corrections, _corrects, _pattern_statuses

# 화면에 보이는 구간 판정
_SHOWN_STATES = (
    SpanMatch.State.DECIDED,
    SpanMatch.State.DIVERGENT,
    SpanMatch.State.UNRESOLVED,
)


def _grammar_response(analysis, offsets, origins, utf16, restore):
    """analysis 이벤트의 문법: 저장 구간을 보이고, 구성 문법은 바깥 항목의 parts에 넣는다(#65)."""
    return _with_parts(_grammar_entries(analysis, offsets, origins, utf16, restore))


def _grammar_entries(analysis, offsets, origins, utf16, restore, excluded=(), span_of=None):
    """용법이 정해진 구간, 해석 갈림, 미확정 구간을 이 요청 원문의 UTF-16 위치로 보인다.
    (항목, 매칭된 패턴의 show_parts) 목록(원문 순서)이다.

    같은 분석을 표기가 다른 원문(앞 공백, 괄호, 숫자 자릿수 등)이 함께 쓰므로, 요청마다
    그 원문 기준으로 다시 계산한다. 검수 상태는 저장하지 않고 볼 때마다 정한다(ADR 0003):
    고른 용법, 그 용법이 속한 패턴, 실제로 매칭된 패턴 중 하나라도 반려됐으면 빼고, 미검수면
    'AI 생성·미검수'다. 해석 갈림의 대안도 하나씩 같게 보고, 반려된 대안만 뺀다(주 용법 쪽이
    반려면 구간째 뺀다). 미확정은 매칭된 패턴만 본다. excluded는 뺄 저장 행 ID다(다시 판정하는
    구간, #176). span_of를 주면 {id(항목): 저장 구간}을 채운다.

    활성 정정이 있는 구간은 저장된 판정 대신 정정 후 용법으로 보이고, 해제면 뺀다. 정정 뒤 다시
    분석하기 전(stale 행의 옛 결과, 재분석 실패로 남은 결과)에도 오답이 보이지 않게 한다(#222).
    """
    spans = list(
        analysis.span_matches.filter(state__in=_SHOWN_STATES)
        .exclude(pk__in=excluded)
        .select_related("pattern__variant_of", "usage__pattern")
        .prefetch_related("pattern__morphemes")
        .order_by("start_offset", "end_offset", "id")
    )
    alternative_usages = GrammarUsage.objects.select_related("pattern").in_bulk(
        [alt["usage_id"] for span in spans for alt in span.alternatives or []]
    )
    corrections = _corrections(analysis)
    entries = []
    for span in spans:
        correction = corrections.get((span.start_offset, span.end_offset))
        if correction is not None and _corrects(correction, span):
            after = correction.after_usage
            if after is None:
                continue
            # 정정 후 용법(그 패턴 포함)이 반려됐으면 분석할 때처럼 정정을 건너뛰고 저장된 판정을
            # 보인다. 읽어 온 행을 바꾸므로 span_of로 받는 쪽(평가, 정정 화면)도 정정 결과를 본다.
            if _review_status(span.pattern, after) is not None:
                span.usage, span.state, span.alternatives = after, SpanMatch.State.DECIDED, None
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
                            "function_tags": usage.function_tags,
                            "function_tags_review_status": usage.function_tags_status,
                            "translation_ko": restore(alt["translation_ko"]),
                            "review_status": review_status,
                        }
                    )
        entries.append((item, span.pattern.show_parts))
        if span_of is not None:
            span_of[id(item)] = span
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
    fields = _usage_fields(pattern, usage)
    if fields is None:
        return None
    start, end = to_original(origins, utf16, *to_analysis(offsets, start_offset, end_offset))
    return {"start": start, "end": end, "state": state, **fields}


def _usage_fields(pattern, usage):
    """문법 카드의 용법 칸(이름·설명·대응 표현·태그·검수 상태·회화체). 반려됐으면 None."""
    review_status = _review_status(pattern, usage)
    if review_status is None:
        return None
    return {
        "pattern_name": pattern.name,
        "name": usage.name,
        "explanation_ko": usage.explanation_ko,
        "korean_equivalent": usage.korean_equivalent,
        "korean_equivalent_review_status": usage.korean_equivalent_status,
        **_tag_fields(pattern, usage),
        "review_status": review_status,
        **_register_fields(pattern),
    }


def _tag_fields(pattern, usage):
    """태그 줄 칸(#151): 실제로 매칭된 패턴의 품사 태그와, 용법의 기능 태그·그 검수 상태.
    용법이 없으면(미확정) 기능 태그는 빈 목록이다.
    """
    return {
        "pos_tags": patterns.pos_tags(pattern),
        "function_tags": usage.function_tags if usage else [],
        "function_tags_review_status": usage.function_tags_status if usage else None,
    }


def _register_fields(pattern):
    """매칭된 패턴의 회화체 표시(#63)와 접속 형태(#229)."""
    base = pattern.variant_of
    return {
        "register": pattern.register,
        "variant_of": base.name if base else None,
        "connection": {
            "pattern_id": pattern.pk,
            "text": pattern.connection_form,
            "review_status": pattern.connection_status,
            "filled": pattern.connection_filled,
        },
    }


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
        "pattern_name": span.pattern.name,
        "name": span.pattern.name,
        "explanation_ko": None,
        "korean_equivalent": None,
        "korean_equivalent_review_status": None,
        **_tag_fields(span.pattern, None),
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
        morph = token_at.get((span["start"], span["end"]))
        reading = words.reading_for(sense, text, morph)
        start, end = to_original(origins, utf16, *to_analysis(offsets, span["start"], span["end"]))
        items.append(
            words.response_item(start, end, sense.word, reading, sense, before_save, morph=morph)
        )
    return items


def _names_response(name_spans, offsets, origins, utf16):
    """저장된 이름 구간(위치·종류)을 이 요청 원문의 UTF-16 위치로 보인다(#140, #184). 판단하지
    않은 행이면 None이다.
    """
    if name_spans is None:
        return None
    names = []
    for span in name_spans:
        start, end = to_original(origins, utf16, *to_analysis(offsets, span["start"], span["end"]))
        names.append({"start": start, "end": end, "type": span["type"]})
    return names


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

    def partial_translation_event(self, prefix):
        """검증 전 번역 앞부분 이벤트(#303). 보낼 만큼 정해진 글이 없으면 None이다. 없는 번호의
        자리표시자를 쓴 앞부분은 숫자를 되돌릴 수 없어 보내지 않는다(번역 검증에서 실패한다).
        """
        settled = settled_prefix(prefix)
        if not settled or not has_only_known_placeholders(settled, self.sentence.numbers):
            return None
        return {"type": "translation_partial", "translation_ko": self.sentence.restore(settled)}

    def locked_analysis_event(self, analysis_id):
        """분석 행을 잠가 다시 읽고 만든 analysis 이벤트와 그 행. 앞서 읽은 행 뒤에 다른 작업이
        번역과 구간을 바꿨어도 옛 번역과 새 문법이 섞이지 않는다(구간을 쓰는 모든 경로가 분석 행을
        잠근 뒤 커밋한다).
        """
        with transaction.atomic():
            row = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=analysis_id)
            return row, self.analysis_event(row)

    def analysis_event(self, saved):
        # 동시에 저장된 다른 요청의 결과를 쓸 수 있어, 문법·단어와 짝인 번역을 함께 싣는다.
        s = self.sentence
        name_spans = _names_response(saved.name_spans, s.offsets, self.origins, self.utf16)
        items = _words_response(
            saved.word_spans, s.text, s.token_at, s.offsets, self.origins, self.utf16
        )
        return {
            "type": "analysis",
            "translation_ko": s.restore(saved.translation_ko),
            "grammar": _grammar_response(saved, s.offsets, self.origins, self.utf16, s.restore),
            "words": self.with_name_words(items, name_spans),
            "name_spans": name_spans,
        }

    def with_name_words(self, items, name_spans):
        """단어가 없는 이름 토큰도 보인다.

        원문 표기는 응답에서만 쓰고 공용 사전에 저장하지 않는다.
        """
        s = self.sentence
        for token, morph in enumerate(s.morphs):
            if not s.is_vocabulary(token) or morph.pos == "接尾辞":
                continue
            start, end = to_original(self.origins, self.utf16, morph.begin, morph.end)
            if not any(n["start"] <= start and end <= n["end"] for n in name_spans or ()):
                continue
            if any(w["start"] < end and start < w["end"] for w in items):
                continue
            reading = words.to_hiragana(morph.reading)
            items.append(
                {
                    "start": start,
                    "end": end,
                    "dictionary_form": self.original[
                        self.origins[morph.begin][0] : self.origins[morph.end - 1][1]
                    ],
                    "reading": reading if words.is_kana(reading) else "",
                    # SudachiPy가 지명으로 본 단어는 행정 단위를 한자음으로 적는다(#267).
                    "reading_ko": (
                        place_reading(s.text[morph.begin : morph.end], reading)
                        if morph.pos3 == "地名"
                        else korean_reading(reading)
                    ),
                    "tags": ["proper_noun"],
                    "in_dictionary": False,
                    "is_name": True,
                    "sense": None,
                }
            )
        return sorted(items, key=lambda item: (item["start"], item["end"]))

    def judged_event(self, spans, word_spans):
        """첫 LLM 응답이 판정한 문법과 고른 뜻(저장 전, #97). spans·word_spans는 작업자 소식이다.

        용법을 고른 구간은 그 용법의 카드가 되고, 해당 없음은 확인 중에서 빠진다. 해석 갈림·미확정·
        미발견은 다시 묻기나 저장을 기다리므로 확인 중으로 남는다. 새 구문은 저장 전에는 패턴이
        없어 analysis에서 보인다. 구간은 (패턴, 토큰 위치)로 이 요청의 후보 구간과 맞춘다.
        word_spans가 None이면 판정 칸만 먼저 온 소식이라(#204) 단어는 먼저 보낸 사전 단어다.
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
            "words": (
                self.sentence_words()
                if word_spans is None
                else _words_response(
                    word_spans, s.text, s.token_at, s.offsets, self.origins, self.utf16, True
                )
            ),
        }

    def grammar_entries(self, analysis, excluded=()):
        """저장 구간의 (항목, show_parts) 목록(원문 순서, _grammar_entries)."""
        s = self.sentence
        return _grammar_entries(analysis, s.offsets, self.origins, self.utf16, s.restore, excluded)

    def grammar_spans(self, analysis):
        """analysis 이벤트의 문법과, 항목마다 그 저장 구간 {id(항목): 구간}(평가 #177)."""
        s, spans = self.sentence, {}
        entries = _grammar_entries(
            analysis, s.offsets, self.origins, self.utf16, s.restore, span_of=spans
        )
        return _with_parts(entries), spans

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
        만든 지식이라 미검수면 미검수로 보인다(불변식). 반려된 용법은 후보에 없다. 후보가 하나면
        판정 전에도 카드를 채우도록 그 용법 칸(usage)을 싣고, 여럿이면 None이다(#203).
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
            usage = (
                _usage_fields(span.pattern, span.candidates[0][1])
                if len(span.candidates) == 1
                else None
            )
            items.append(
                {
                    "start": start,
                    "end": end,
                    "pattern_name": span.pattern.name,
                    "connection": _register_fields(span.pattern)["connection"],
                    "candidates": candidates,
                    "usage": usage,
                }
            )
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
                        start,
                        end,
                        only.sense.word,
                        only.reading,
                        only.sense,
                        before_save=True,
                        morph=morphs[token],
                    )
                )
                continue
            item = words.response_item(
                start, end, cands[0].sense.word, cands[0].reading, None, morph=morphs[token]
            )
            item["reading"] = "・".join(dict.fromkeys(c.reading for c in cands))
            item["tags"] = sorted(
                set.intersection(
                    *(set(words.word_tags(c.sense.word, morphs[token])) for c in cands)
                )
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
