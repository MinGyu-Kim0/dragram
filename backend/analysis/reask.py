"""첫 응답의 새 구문 정리와, 해석 갈림·미확정 구간·같은 조건 패턴을 한 번에 다시 묻기."""

from analysis import morphology, patterns
from analysis.answers import FIRST_VERDICTS, RECHECK_VERDICTS, _is_text, _validate_judgement
from analysis.models import ReviewStatus, SpanMatch
from analysis.normalize import has_all_placeholders
from analysis.sentence import _decided_span, _llm_spans, _pattern_statuses
from errors import AnalysisError, BusinessError


def _new_pattern_conditions(tokens, morphs, overlaps_number):
    """새 구문의 토큰 표시로 형태소 조건을 만든다. 패턴 생성 규칙에 어긋나면 None."""
    ids = [token for token, _ in tokens]
    # 패턴은 연속한 토큰만 다루므로 처음부터 끝까지 빠짐없이 차례로 표시해야 한다.
    if ids != list(range(ids[0], ids[0] + len(ids))):
        return None
    if tokens[0][1] == "any" or tokens[-1][1] == "any":
        return None
    # 숫자 토큰의 lemma는 원문 숫자다. 고정하면 공용 패턴에 원문 숫자가 들어가고, 숫자만 다른
    # 문장(키 텍스트가 같다)에는 걸리지 않는다.
    if any(fix != "any" and overlaps_number(token) for token, fix in tokens):
        return None
    conditions = [patterns.condition(morphs[token], fix) for token, fix in tokens]
    # 내용어만 고정한 패턴은 그 구절에만 걸린다(#133). 아무거나 조건은 pos1이 None이다.
    if not any(c.pos1 in morphology.FUNCTION_POS for c in conditions):
        return None
    # 만든 패턴이 원래 문장의 그 자리에 다시 걸려야 저장한다.
    if not patterns.matches_at(conditions, morphs, ids[0]):
        return None
    return conditions


def _reading_changed(first, again):
    """해석 갈림·미확정이던 구간의 주 해석이 다시 묻기에서 바뀌었는가(번역을 바꿀지).

    주 해석은 고른 용법(해석 갈림이면 주 용법)이거나 '해당 없음'이다. 다시 물어도 미확정이면
    바뀌지 않은 것으로 보고, 처음에 미확정이었으면 무엇이 오든 바뀐 것이다.
    """
    if again[0] == SpanMatch.State.UNRESOLVED:
        return False
    if first[0] == SpanMatch.State.UNRESOLVED:
        return True
    return again[1] != first[1]


def prepare(sentence, validated):
    """새 구문마다 형태소 조건을 만든다. 패턴 생성 규칙을 어겼으면 None이다. 같은 자리에서
    이미 판정한 후보 구간이나 앞서 낸 새 구문과 패턴이 같은 제안은 같은 구간이므로 뺀다.
    후보 구간과 토큰 범위가 같은 제안은 조건이 달라도 뺀다(#233). 판정할 후보 구간도 함께 둔다.
    """
    s = sentence
    # morpheme_key가 같으면 토큰 수도 같으므로 (key, 시작 토큰)이 같으면 같은 구간이다.
    placed = {(span.pattern.morpheme_key, span.start_token) for span in s.matched}
    # 활용형만 더 고정한 제안은 key가 달라 위에서 걸리지 않고 중복 패턴이 된다. 기존 용법이
    # 안 맞으면 그 후보 구간의 미발견이 같은 패턴 아래 새 용법으로 처리한다.
    ranges = {(span.start_token, span.end_token) for span in s.matched}
    new_patterns = []
    for proposal in validated["new_patterns"]:
        if (proposal["tokens"][0][0], proposal["tokens"][-1][0]) in ranges:
            continue
        conditions = _new_pattern_conditions(proposal["tokens"], s.morphs, s.overlaps_number)
        if conditions is not None:
            place = (patterns.morpheme_key(conditions), proposal["tokens"][0][0])
            if place in placed:
                continue
            placed.add(place)
        new_patterns.append({**proposal, "conditions": conditions, "existing": None})
    return {**validated, "new_patterns": new_patterns, "span_list": s.spans}


def ask_again(sentence, client, validated, job_outdated):
    """첫 응답의 해석 갈림·미확정 구간과, 형태소 조건이 같은 패턴이 이미 있는 새 구문을 한
    요청으로 다시 묻는다(#40). 이 호출이 마지막이다.

    같은 조건의 새 구문은 새 용법을 버리고 그 패턴의 기존 용법 목록으로 묻고, 물은 구간은
    판정할 후보 구간으로 옮긴다. 반려된 패턴이면 묻지 않고 미발견으로 남긴다. 해석 갈림·
    미확정 구간은 한 번만 묻는다(_PatternTaken 뒤 다시 부를 때는 빼고, 그 답은 다시 묻지
    않는다). 그 구간의 주 해석이 바뀌었을 때만 다시 받은 번역으로 바꾼다.
    """
    s = sentence
    recheck = (
        []
        if validated.get("rechecked")
        else [
            index
            for index, (state, _, _) in enumerate(validated["spans"])
            if state in (SpanMatch.State.DIVERGENT, SpanMatch.State.UNRESOLVED)
        ]
    )
    recheck_spans = [validated["span_list"][index] for index in recheck]
    proposals = validated["new_patterns"]
    existing = patterns.existing_patterns(
        [p["conditions"] for p in proposals if p["conditions"] is not None]
    )
    rest, asked = [], []
    # 후보 ID가 다시 묻는 구간끼리 겹치지 않게 이어 매긴다.
    next_id = 1 + max(
        (candidate_id for span in recheck_spans for candidate_id, _ in span.candidates),
        default=0,
    )
    for proposal in proposals:
        pattern = None
        if proposal["conditions"] is not None:
            pattern = existing.get(patterns.morpheme_key(proposal["conditions"]))
        if pattern is None:
            rest.append(proposal)
        elif ReviewStatus.REJECTED in _pattern_statuses(pattern):
            rest.append({**proposal, "existing": pattern})
        else:
            span = patterns.span_of(pattern, proposal["tokens"][0][0], next_id)
            next_id += len(span.candidates)
            asked.append(span)
    if not asked and not recheck:
        return {**validated, "new_patterns": rest}
    if job_outdated():
        # 저장하지 않을 결과라 버려질 재질문을 보내지 않는다.
        return validated
    llm_spans = _llm_spans(recheck_spans + asked)
    # 해석이 정해진 구간은 그 해석대로 번역하게 알린다(답은 받지 않는다).
    decided = [
        _decided_span(span.start_token, span.end_token, usage)
        for span, (state, usage, _) in zip(validated["span_list"], validated["spans"], strict=True)
        if state == SpanMatch.State.DECIDED
    ]
    result = client.judge_spans(
        s.key_text,
        s.tokens,
        validated["translation_ko"],
        s.decided_spans + decided,
        llm_spans[: len(recheck)],
        llm_spans[len(recheck) :],
    )

    def final_translation(answers):
        """다시 물은 구간의 주 해석이 바뀌었을 때만 다시 받은 번역을 쓴다."""
        if not any(
            _reading_changed(validated["spans"][index], answers[k])
            for k, index in enumerate(recheck)
        ):
            return validated["translation_ko"]
        translation = result.get("translation_ko")
        if not _is_text(translation) or not has_all_placeholders(translation, s.numbers):
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 다시 묻기 번역")
        return translation

    answers, new_alternatives, translation = _validate_judgement(
        result,
        recheck_spans + asked,
        [RECHECK_VERDICTS] * len(recheck) + [FIRST_VERDICTS] * len(asked),
        s.numbers,
        "다시 묻기",
        final_translation,
    )
    spans = list(validated["spans"])
    # 대안은 판정할 후보 구간 목록의 순번으로 둔다.
    positions = recheck + list(range(len(spans), len(spans) + len(asked)))
    for k, index in enumerate(recheck):
        spans[index] = answers[k]
    return {
        **validated,
        "translation_ko": translation,
        "new_patterns": rest,
        "spans": spans + answers[len(recheck) :],
        "span_list": validated["span_list"] + asked,
        "alternatives": {
            **validated.get("alternatives", {}),
            **{positions[k]: alts for k, alts in new_alternatives.items()},
        },
        "rechecked": True,
    }
