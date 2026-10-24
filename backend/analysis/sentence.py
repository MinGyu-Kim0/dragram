"""분석 텍스트에서 계산되는 값. 요청과 작업자가 함께 쓴다."""

import hashlib

from analysis import patterns, words
from analysis.models import ReviewStatus, SentenceAnalysis, UsageRule
from analysis.morphology import morphemes
from analysis.normalize import key_pieces, number_ends, restore_numbers
from analysis.positions import key_offsets, to_key
from analysis.rules import condition_matches
from errors import AnalysisError, BusinessError


def _numbers_before_particle(text, morphs):
    """원문에서 바로 뒤에 조사(助詞)가 오는 숫자의 자리표시자 번호."""
    particle_starts = {m.begin for m in morphs if m.pos == "助詞"}
    return {n for n, end in enumerate(number_ends(text), start=1) if end in particle_starts}


# 학습할 단어가 아닌 토큰의 품사(문장부호, 공백, 문법 쪽에서 다루는 조사·조동사)
_NON_WORD_POS = {"補助記号", "空白", "助詞", "助動詞"}


def _pattern_statuses(pattern):
    """매칭된 패턴과, 연결됐으면 그 원형의 검수 상태들(#63)."""
    base = pattern.variant_of
    return {pattern.status} | ({base.status} if base else set())


def _closed_usage(span):
    """용법 완결로 LLM 없이 확정할 구간이면 (후보 ID, 그 용법), 아니면 None(구간 판정 절차
    2단계). 승인된 용법 완결 패턴이고, 반려되지 않은 용법이 승인된 하나뿐이어야 한다. 용법 완결
    표시가 보장하지만 분석 때도 다시 본다.
    """
    pattern = span.pattern
    # 연결된 회화체는 원형도 승인돼야 한다. 후보는 원형의 용법이다(#63).
    if not pattern.usage_closed or _pattern_statuses(pattern) != {ReviewStatus.APPROVED}:
        return None
    if len(span.candidates) != 1:
        return None
    candidate = span.candidates[0]
    return candidate if candidate[1].status == ReviewStatus.APPROVED else None


def _approved_rules(spans):
    """구간들의 매칭된 패턴에 걸린 승인된 판별 규칙. {패턴 ID: [규칙](id 순서)}(#55)."""
    rules = {}
    approved = UsageRule.objects.filter(
        status=UsageRule.Status.APPROVED, pattern__in={span.pattern.pk for span in spans}
    ).order_by("id")
    for rule in approved:
        rules.setdefault(rule.pattern_id, []).append(rule)
    return rules


def _rule_usage(span, morphs, rules):
    """승인된 판별 규칙으로 LLM 없이 확정할 구간이면 (후보 ID, 용법, 규칙), 아니면 None(구간 판정
    절차 3단계, #55). 후보가 하나여도, 같은 패턴에 미검수 용법이 있어도 적용한다.

    실제로 매칭된 패턴의 규칙 가운데 패턴(연결됐으면 원형도)과 용법이 승인됐고 용법이 후보에 있는
    것만 본다. 분석할 때 상태를 다시 본다. 조건이 맞는 규칙들이 가리키는 후보가 정확히 하나일
    때만 확정하고, 같은 용법을 가리키는 규칙이 여럿 맞으면 id가 가장 작은 규칙을 기록한다.
    """
    if _pattern_statuses(span.pattern) != {ReviewStatus.APPROVED}:
        return None
    candidates = {usage.id: (candidate_id, usage) for candidate_id, usage in span.candidates}
    decided = {}
    for rule in rules.get(span.pattern.pk, ()):
        candidate = candidates.get(rule.usage_id)
        if candidate is None or candidate[1].status != ReviewStatus.APPROVED:
            continue
        if condition_matches(rule.condition, morphs, span.start_token, span.end_token):
            decided.setdefault(rule.usage_id, rule)
    if len(decided) != 1:
        return None
    [(usage_id, rule)] = decided.items()
    return (*candidates[usage_id], rule)


def _llm_spans(spans):
    """LLM에 줄 후보 구간. 구간 ID는 이 목록의 순번이다. 원형에 연결된 회화체 구간은 원형 패턴
    이름(colloquial_of)을 함께 준다. 후보는 원형의 용법이다(#63).
    """
    return [
        {
            "span_id": span_id,
            "start_token_id": span.start_token,
            "end_token_id": span.end_token,
            **({"colloquial_of": span.pattern.variant_of.name} if span.pattern.variant_of else {}),
            "candidates": [
                {"candidate_id": candidate_id, "name": u.name, "explanation_ko": u.explanation_ko}
                for candidate_id, u in span.candidates
            ],
        }
        for span_id, span in enumerate(spans)
    ]


def _is_fresh(analysis):
    """다시 분석하지 않고 쓸 수 있는 분석인가."""
    return analysis.word_spans is not None and not analysis.is_stale


class Sentence:
    """분석 텍스트 하나에서 정해지는 값. 원문 기준 위치·표시는 Presenter가 맡는다.

    만들 때 그 문장의 분석 행과 패턴 세트 버전을 읽고 등록된 패턴에 매칭한다. 캐시 분석이 없으면
    사전에서 단어도 찾는다.
    """

    def __init__(self, text):
        if not text:
            raise BusinessError(AnalysisError.TEXT_REQUIRED, "정규화 후 빈 문장")
        self.text = text
        self.pieces, self.numbers = key_pieces(text)
        self.key_text = "".join(self.pieces)
        self.sentence_hash = hashlib.sha256(self.key_text.encode()).hexdigest()

        # 형태소 분석은 숫자가 그대로인 분석 텍스트로 한다. 숫자 뒤 조사 교정에 쓰므로 캐시를
        # 재사용할 때도 한다. 원문은 로그에 남기지 않는다.
        self.morphs = morphemes(text)
        self.particle_numbers = _numbers_before_particle(text, self.morphs)
        self.offsets = key_offsets(self.pieces)
        # 저장된 단어 위치(키 텍스트 구간) → 이 문장의 형태소
        self.token_at = {to_key(self.offsets, m.begin, m.end): m for m in self.morphs}

        # 단어 칸을 받기 전에 저장된 행(word_spans가 NULL)과 stale 행은 다시 분석한다.
        self.existing = SentenceAnalysis.objects.filter(sentence_hash=self.sentence_hash).first()
        existing = self.existing
        self.cached = existing if existing is not None and _is_fresh(existing) else None
        # 다시 분석하는 동안 영향 범위의 패턴·용법 상태가 바뀌면 이 값이 올라 저장하지 않는다.
        self.started_generation = existing.generation if existing is not None else 0
        # 분석에는 매칭(candidate_spans) 직전에 읽은 패턴 세트 버전을 기록한다. 그 뒤에
        # 활성화된 패턴은 다음 조회가 다시 매칭해 찾는다. 캐시 분석의 버전이 이보다 낮으면 다시
        # 매칭한다(#41).
        self.matcher_version = patterns.pattern_set_version()

        # LLM에는 키 텍스트 기준 표층형을 보내 원문 숫자가 가지 않게 한다.
        self.tokens = [
            {"id": i, "surface": "".join(self.pieces[m.begin : m.end])}
            for i, m in enumerate(self.morphs)
        ]

        # 등록된 패턴에 걸린 구간과 후보 용법. LLM은 서버가 매긴 구간·후보 ID로만 답한다.
        # 승인된 용법 완결 패턴의 구간(#39)과 승인된 판별 규칙으로 정해지는 구간(#55)은 LLM 없이
        # 확정하고, 나머지만 후보로 묻는다. 확정 구간은 LLM이 새 구문으로 다시 내지 않도록 알리기만
        # 한다.
        self.matched = patterns.candidate_spans(self.morphs)
        self.rules = _approved_rules(self.matched)
        # (구간, 후보 ID, 용법, 판별 규칙(용법 완결 확정이면 None))
        self.closed_spans, self.spans = [], []
        for span in self.matched:
            closed = _closed_usage(span)
            if closed is not None:
                self.closed_spans.append((span, *closed, None))
            elif (by_rule := _rule_usage(span, self.morphs, self.rules)) is not None:
                self.closed_spans.append((span, *by_rule))
            else:
                self.spans.append(span)
        self.llm_spans = _llm_spans(self.spans)
        self.decided_spans = [
            {"start_token_id": span.start_token, "end_token_id": span.end_token, "name": usage.name}
            for span, _, usage, _ in self.closed_spans
        ]
        self.content_tokens = sum(m.pos not in {"補助記号", "空白"} for m in self.morphs)

        # 학습 단어(조사·조동사·기호·숫자를 뺀 토큰)를 모두 JMdict에서 찾는다. 후보 뜻이 하나면
        # LLM 없이 정하고, 여럿이면 새 문장 LLM 요청에서 함께 고르게 한다. 못 찾은 토큰은 보이지도
        # 기록하지도 않는다(#96, 사전에 없는 단어는 #97).
        # 캐시 분석은 저장된 단어를 쓰므로 찾지 않는다.
        self.found = (
            {}
            if self.cached
            else words.lookup(
                text,
                self.morphs,
                [token for token in range(len(self.morphs)) if self.is_vocabulary(token)],
            )
        )
        self.ambiguous = {token: cands for token, cands in self.found.items() if len(cands) > 1}
        self.llm_words = [
            {"token_id": token, "candidates": words.llm_candidates(cands)}
            for token, cands in self.ambiguous.items()
        ]

    def restore(self, text):
        return restore_numbers(text, self.numbers, self.particle_numbers)

    def overlaps_number(self, token):
        # 숫자열은 자리표시자 조각과 빈 조각(뒤쪽 숫자)으로 이뤄진다.
        m = self.morphs[token]
        return any(piece == "" or "⟨N" in piece for piece in self.pieces[m.begin : m.end])

    def is_vocabulary(self, token):
        # 숫자는 학습할 단어가 아니고, 숫자열과 겹치는 토큰(X12의 X1, 2)은 LLM이 사전형에
        # 숫자를 지어내면 숫자만 다른 문장에 잘못 재사용된다.
        return self.morphs[token].pos not in _NON_WORD_POS and not self.overlaps_number(token)

    def key_span(self, start_token, end_token):
        return to_key(self.offsets, self.morphs[start_token].begin, self.morphs[end_token].end)

    def span_key(self, span):
        """구간의 열쇠: (패턴 ID, 키 텍스트 start, end)."""
        return (span.pattern.id, *self.key_span(span.start_token, span.end_token))

    def word_spans(self, chosen):
        """저장할 단어 위치와 뜻(토큰 순서). chosen은 LLM이 고른 {토큰: 뜻 ID}다."""
        stored = []
        for token, cands in self.found.items():
            sense_id = cands[0].sense.id if len(cands) == 1 else chosen.get(token)
            if sense_id is not None:
                start, end = self.key_span(token, token)
                stored.append({"start": start, "end": end, "sense_id": sense_id})
        return stored
