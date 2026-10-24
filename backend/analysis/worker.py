"""작업자의 분석 실행과 저장(#98, ADR 0005)."""

from django.db import IntegrityError, transaction

from analysis import jobs, llm, morphology, patterns, words
from analysis.answers import (
    FIRST_VERDICTS,
    RECHECK_VERDICTS,
    _is_text,
    _quotes_whole_sentence,
    _validate,
    _validate_definitions,
    _validate_meanings,
    _validate_recheck_answers,
    _validate_translation,
    reject_quotes,
)
from analysis.examples import _check_examples
from analysis.models import ReviewStatus, SentenceAnalysis, SpanMatch, UsageLog
from analysis.normalize import has_all_placeholders
from analysis.sentence import Sentence, _llm_spans, _pattern_statuses
from analysis.span_rows import _basis_changed, _is_place_conflict, _PatternTaken, span_matches
from analysis.usage import RequestUsage
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error


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


def _sense_ids(word_spans):
    """word_spans의 뜻 ID를 중복 없이 모은다."""
    return sorted({span["sense_id"] for span in word_spans})


def _judged_spans(spans, answers):
    """첫 응답이 판정한 후보 구간을 저장 전에 알릴 소식(#97). 패턴·용법 ID와 토큰 위치만 싣는다."""
    return [
        {
            "pattern_id": span.pattern.id,
            "start_token": span.start_token,
            "end_token": span.end_token,
            "state": state,
            "usage_id": usage.id if state == SpanMatch.State.DECIDED else None,
        }
        for span, (state, usage, _) in zip(spans, answers, strict=True)
    ]


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


def _attempt(started):
    """작업 소식에 싣는 시도 식별자. 선점할 때마다 새로 쓰는 processing_started_at이다.

    세대 번호는 검수 사건으로도 올라 시도를 가르지 못한다. 구독한 뒤 다시 선점한 요청이 앞
    시도의 소식을 자기 것으로 받지 않게 한다.
    """
    return started.isoformat() if started else None


def _fail(analysis_id, started, code):
    """그 시도(started)로 처리 중인 분석 행을 실패로 두고 알린다. 다음 요청이 다시 선점한다."""
    SentenceAnalysis.objects.filter(
        pk=analysis_id,
        status=SentenceAnalysis.Status.PROCESSING,
        processing_started_at=started,
    ).update(status=SentenceAnalysis.Status.FAILED, processing_translation_ko=None)
    sentence_hash = (
        SentenceAnalysis.objects.filter(pk=analysis_id)
        .values_list("sentence_hash", flat=True)
        .first()
    )
    if sentence_hash is not None:
        message = {"type": "failed", "error": code, "attempt": _attempt(started)}
        jobs.publish(sentence_hash, message)


def run_analysis(analysis_id, text, usage_id):
    """작업자가 실행하는 분석 LLM 작업(analysis.jobs). text는 요청이 정규화한 분석 텍스트다.

    정규화는 두 번 적용하면 결과가 달라질 수 있어(공백을 지운 뒤 결합 탁점이 합쳐지는 등) 다시
    하지 않는다. 그러지 않으면 해시가 달라져 요청이 선점한 행을 찾지 못한다.
    """
    started = (
        SentenceAnalysis.objects.filter(pk=analysis_id)
        .values_list("processing_started_at", flat=True)
        .first()
    )
    try:
        Worker(Sentence(text)).run(analysis_id, usage_id)
    except BaseException:
        # 우리 코드의 버그와 작업 시간 초과(RQ가 작업 안에서 올린다)도 실패로 알린 뒤 그대로
        # 올린다. 기다리는 요청이 대기 상한까지 붙잡히거나 행이 처리 중에 남지 않게 한다.
        _fail(analysis_id, started, AnalysisError.FAILED.code)
        raise


class Worker:
    """선점된 분석 행 하나의 LLM 분석과 저장.

    이 작업의 LLM 호출(분석·다시 묻기·예문 다시 쓰기)은 한 클라이언트(client)로 해서 요청 전체
    마감 시각을 함께 쓴다. usage는 선점한 요청의 사용 기록이다. 둘 다 run이 채운다.
    """

    def __init__(self, sentence):
        self.sentence = sentence
        self.client = self.usage = None

    def run(self, analysis_id, usage_id):
        """선점된 분석 행(analysis_id)을 분석한다. usage_id는 선점한 요청의 request 기록이다.

        저장에 성공하면 done, 실패하면 failed 소식을 보낸다. 그 밖의 예외는 run_analysis가 실패로
        알린다.
        """
        existing = self.sentence.existing
        if existing is None or existing.pk != analysis_id:
            raise RuntimeError(f"분석 텍스트의 해시가 분석 행과 다름: analysis_id={analysis_id}")
        self.usage = RequestUsage(UsageLog.objects.get(pk=usage_id))
        self.client = llm.get_client(self.usage.record_llm)
        try:
            self.work()
        except BusinessError as e:
            log_business_error(e)
            _fail(analysis_id, existing.processing_started_at, e.error_code.code)
            return
        if SentenceAnalysis.objects.filter(
            pk=analysis_id, status=SentenceAnalysis.Status.PROCESSING
        ).exists():
            # 저장하지 못하고 끝났다(다른 쓰기가 같은 구간을 먼저 넣음).
            _fail(analysis_id, existing.processing_started_at, AnalysisError.FAILED.code)
            return
        self.usage.succeed()
        self.publish({"type": "done"})

    def work(self):
        """LLM 분석을 하고 저장한다. 번역을 검증하자마자 먼저 알리고, 문법·단어까지 검증해
        저장한다. 실패하면 BusinessError이고 어느 단계에서 실패해도 저장하지 않는다.
        """
        s = self.sentence
        translated = False
        result = None
        for kind, value in self.client.analyze_stream(
            s.key_text, s.tokens, s.llm_spans, s.decided_spans, s.llm_words, s.unknown
        ):
            if kind == "translation":
                _validate_translation(value, s.numbers)
                translated = True
                self.share_translation(value)
            else:
                result = value
        validated = _validate(
            result,
            s.numbers,
            len(s.morphs),
            s.spans,
            s.ambiguous,
            {token: s.text[s.morphs[token].begin : s.morphs[token].end] for token in s.unknown},
        )
        if not translated:
            self.share_translation(validated["translation_ko"])
        # 거부될 응답이면 다시 묻지 않는다.
        reject_quotes(validated, s)
        stored_words = s.word_spans(validated["words"])
        if s.spans or s.ambiguous:
            self.publish(
                {
                    "type": "judged",
                    "spans": _judged_spans(s.spans, validated["spans"]),
                    "word_spans": stored_words,
                }
            )
        # 다시 묻기는 번역을 알린 뒤, 저장 트랜잭션 밖에서 한다.
        asked = self.ask_again(self.prepare(validated))
        # 사전에 없던 단어는 저장 전에 2단계로 만들어 analysis에 함께 싣는다(#134). 꼭 해야 하는
        # 다시 묻기가 요청 마감을 먼저 쓰도록 그 뒤에 한다.
        asked["words"] = {**asked["words"], **self.define_words(validated["new_words"])}
        stored_words = s.word_spans(asked["words"])
        self.save(asked)
        # 한국어 뜻은 저장한 뒤 만든다. 느리거나 실패해도 분석은 이미 저장돼 있고, 요청 마감을
        # 다시 묻기·예문 다시 쓰기보다 먼저 쓰지 않는다. 새 한국어 뜻은 done 뒤 analysis에 실린다.
        self.make_meanings(_sense_ids(stored_words))

    def define_words(self, new_words):
        """사전에 없던 토큰의 2단계(#134). {토큰: 사전형·읽기}를 받아 {토큰: 뜻 ID}를 돌려준다.

        받은 사전형·읽기로 다시 찾아, 기존 단어면 그 후보에서 고르게 하고 맞는 뜻이 없으면 그 단어
        아래 미검수 뜻을 더한다. 기존 단어가 없으면 사전 항목 없는 단어와 뜻을 만든다. 호출이
        실패하거나 답이 틀린 단어는 빼고, 분석은 계속한다.
        """
        if not new_words or self.job_outdated():
            return {}
        asked, items = [], []
        for word_id, (token, (form, reading)) in enumerate(sorted(new_words.items())):
            candidates = words.find_again(form, reading)
            asked.append((token, form, reading, candidates))
            items.append(
                {
                    "word_id": word_id,
                    "token_id": token,
                    "dictionary_form": form,
                    "reading": reading,
                    "candidates": words.llm_candidates(candidates),
                }
            )
        try:
            result = self.client.define_words(self.sentence.key_text, items)
        except BusinessError as e:
            log_business_error(e)
            return {}
        answers = _validate_definitions(
            result, {i: {c.sense.id for c in cands} for i, (*_, cands) in enumerate(asked)}
        )
        s = self.sentence
        chosen = {}
        for word_id, (sense_id, meaning, sense_tags, word_tags) in answers.items():
            token, form, reading, candidates = asked[word_id]
            # 새 뜻은 공용 테이블에 들어가므로 문장 전체를 인용한 뜻은 그 단어만 뺀다.
            if meaning and _quotes_whole_sentence([meaning], s.key_text, s.content_tokens):
                continue
            if sense_id is None:
                # 다시 찾은 단어가 여럿이면 앞의 것(흔한 단어 → JMdict 번호 순)에 더한다.
                word = (
                    candidates[0].sense.word
                    if candidates
                    else words.get_or_make_word(form, reading, word_tags)
                )
                sense_id = words.add_llm_sense(word, meaning, sense_tags).id
            chosen[token] = sense_id
        return chosen

    def make_meanings(self, sense_ids):
        """고른 뜻 가운데 한국어 뜻이 없는 뜻을 LLM 호출 한 번(word_gloss)으로 만든다(#97).

        실패하거나 응답이 틀리면 만들지 못한 뜻만 생성 실패로 둔다.
        """
        senses = words.missing_meanings(sense_ids)
        if not senses:
            return
        asked = [sense.id for sense in senses]
        try:
            result = self.client.gloss_words([words.gloss_input(sense) for sense in senses])
        except BusinessError as e:
            log_business_error(e)
            result = None
        words.save_meanings(asked, _validate_meanings(result, set(asked)))

    def share_translation(self, translation):
        """검증한 번역을 먼저 저장하고 알린다. 늦게 붙은 요청은 저장된 번역을 읽는다."""
        SentenceAnalysis.objects.filter(
            pk=self.sentence.existing.pk, status=SentenceAnalysis.Status.PROCESSING
        ).update(processing_translation_ko=translation)
        self.publish({"type": "translation", "translation_ko": translation})

    def publish(self, message):
        """이 시도의 작업 소식을 보낸다."""
        s = self.sentence
        jobs.publish(
            s.sentence_hash, {**message, "attempt": _attempt(s.existing.processing_started_at)}
        )

    def prepare(self, validated):
        """새 구문마다 형태소 조건을 만든다. 패턴 생성 규칙을 어겼으면 None이다. 같은 자리에서
        이미 판정한 후보 구간이나 앞서 낸 새 구문과 패턴이 같은 제안은 같은 구간이므로 뺀다.
        판정할 후보 구간도 함께 둔다.
        """
        s = self.sentence
        # morpheme_key가 같으면 토큰 수도 같으므로 (key, 시작 토큰)이 같으면 같은 구간이다.
        placed = {(span.pattern.morpheme_key, span.start_token) for span in s.matched}
        new_patterns = []
        for proposal in validated["new_patterns"]:
            conditions = _new_pattern_conditions(proposal["tokens"], s.morphs, s.overlaps_number)
            if conditions is not None:
                place = (patterns.morpheme_key(conditions), proposal["tokens"][0][0])
                if place in placed:
                    continue
                placed.add(place)
            new_patterns.append({**proposal, "conditions": conditions, "existing": None})
        return {**validated, "new_patterns": new_patterns, "span_list": s.spans}

    def job_outdated(self):
        """이 작업의 결과가 버려질 것인가. 시작한 뒤 세대 번호가 올랐으면 저장하지 않는다(save)."""
        s = self.sentence
        return (
            SentenceAnalysis.objects.filter(pk=s.existing.pk)
            .exclude(generation=s.started_generation)
            .exists()
        )

    def ask_again(self, validated):
        """첫 응답의 해석 갈림·미확정 구간과, 형태소 조건이 같은 패턴이 이미 있는 새 구문을 한
        요청으로 다시 묻는다(#40). 이 호출이 마지막이다.

        같은 조건의 새 구문은 새 용법을 버리고 그 패턴의 기존 용법 목록으로 묻고, 물은 구간은
        판정할 후보 구간으로 옮긴다. 반려된 패턴이면 묻지 않고 미발견으로 남긴다. 해석 갈림·
        미확정 구간은 한 번만 묻는다(_PatternTaken 뒤 다시 부를 때는 빼고, 그 답은 다시 묻지
        않는다). 그 구간의 주 해석이 바뀌었을 때만 다시 받은 번역으로 바꾼다.
        """
        s = self.sentence
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
        if self.job_outdated():
            # 저장하지 않을 결과라 버려질 재질문을 보내지 않는다.
            return validated
        llm_spans = _llm_spans(recheck_spans + asked)
        # 해석이 정해진 구간은 그 해석대로 번역하게 알린다(답은 받지 않는다).
        decided = [
            {"start_token_id": span.start_token, "end_token_id": span.end_token, "name": usage.name}
            for span, (state, usage, _) in zip(
                validated["span_list"], validated["spans"], strict=True
            )
            if state == SpanMatch.State.DECIDED
        ]
        result = self.client.judge_spans(
            s.key_text,
            s.tokens,
            validated["translation_ko"],
            s.decided_spans + decided,
            llm_spans[: len(recheck)],
            llm_spans[len(recheck) :],
        )
        if not isinstance(result, dict):
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 다시 묻기")
        checked = _validate_recheck_answers(
            result.get("spans"),
            recheck_spans + asked,
            [RECHECK_VERDICTS] * len(recheck) + [FIRST_VERDICTS] * len(asked),
            s.numbers,
        )
        if checked is None:
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 다시 묻기")
        answers, new_alternatives = checked
        translation = validated["translation_ko"]
        if any(
            _reading_changed(validated["spans"][index], answers[k])
            for k, index in enumerate(recheck)
        ):
            translation = result.get("translation_ko")
            if not _is_text(translation) or not has_all_placeholders(translation, s.numbers):
                raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 다시 묻기 번역")
        # 대안 번역이 최종 번역과 같으면 갈린 해석이 아니다.
        if any(
            alt.strip() == translation.strip()
            for alts in new_alternatives.values()
            for _, alt in alts
        ):
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 대안 번역")
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

    def save(self, validated, final=False):
        """검증한 결과를 공용 캐시에 저장한다.

        저장하는 사이 다른 요청이 같은 조건의 패턴을 먼저 등록했으면, 저장을 되돌리고 그 패턴의
        용법 목록으로 다시 물은 뒤 한 번만 다시 저장한다. 분석하는 사이 영향 범위가 바뀌었으면
        저장하지 않고 ANALYSIS:FAILED다. 다음 요청이 다시 선점해 분석한다(#98).
        """
        s = self.sentence
        # 다시 물어 받은 새 용법도 공용 테이블에 들어가므로 다시 본다.
        reject_quotes(validated, s)
        _check_examples(
            validated, self.client, s.key_text, s.content_tokens, s.key_span, self.job_outdated
        )
        stored_words = s.word_spans(validated["words"])

        try:
            with transaction.atomic():
                outdated = self.save_once(validated, stored_words, final)
                if outdated:
                    transaction.set_rollback(True)
        except _PatternTaken:
            # LLM 호출은 트랜잭션 밖에서 한다.
            self.save(self.ask_again(validated), final=True)
            return
        if outdated:
            raise BusinessError(AnalysisError.FAILED, "분석하는 사이 영향 범위가 바뀜")

    def save_once(self, validated, stored_words, final):
        """선점한 분석 행을 이번 결과로 통째로 바꾸고 완료로 둔다. 시작 뒤 세대 번호나 판정 근거가
        바뀌었으면 참이다(호출하는 쪽이 되돌린다). 호출하는 쪽이 트랜잭션을 연다.

        상태 전이(analysis.review)가 패턴 → 패턴 세트 버전 → 분석 순서로 잠그므로, 분석 행은 패턴
        쪽을 다 쓴 뒤 잠근다. 구간은 분석 행을 잠근 뒤 지우고 넣는다. 구간을 쓰는 모든 경로가 이
        순서라 같은 구간이 겹쳐 들어가지 않는다(#41).
        """
        s = self.sentence
        patterns.lock_links()
        try:
            with transaction.atomic():
                rows = span_matches(s, s.existing, validated, final)
                locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(
                    pk=s.existing.pk
                )
                locked.span_matches.all().delete()
                SpanMatch.objects.bulk_create(rows)
        except IntegrityError as e:
            # 순서를 지키지 않은 쓰기가 같은 구간을 먼저 넣었다. 저장하지 못한 채 끝나 run이
            # 실패로 알린다.
            if not _is_place_conflict(e):
                raise
            return False
        locked.status = SentenceAnalysis.Status.COMPLETE
        locked.translation_ko = validated["translation_ko"]
        locked.processing_translation_ko = None
        locked.word_spans = stored_words
        locked.sense_ids = _sense_ids(stored_words)
        locked.is_stale = False
        # 세대 번호가 같으면 그사이 더 높은 버전으로 저장된 적이 없지만, 값은 낮추지 않는다.
        locked.matcher_version = max(locked.matcher_version, s.matcher_version)
        locked.save(
            update_fields=[
                "status",
                "translation_ko",
                "processing_translation_ko",
                "word_spans",
                "sense_ids",
                "is_stale",
                "matcher_version",
                "updated_at",
            ]
        )
        return locked.generation != s.started_generation or _basis_changed(rows, s.rules)
