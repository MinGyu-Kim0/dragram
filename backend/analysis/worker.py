"""작업자의 분석 실행과 저장(#98, ADR 0005)."""

import math
import os
import socket
import time

from django.utils import timezone

from analysis import analysis_store, jobs, limits, llm, reask, timing
from analysis.answers import (
    SpanAnswersRejected,
    _quotes_whole_sentence,
    _validate,
    _validate_span_answers,
    _validate_translation,
    _validate_word_answers,
    reject_quotes,
)
from analysis.examples import _check_examples
from analysis.models import SentenceAnalysis, SpanMatch
from analysis.sentence import Sentence
from analysis.span_rows import _PatternTaken
from analysis.usage import RequestUsage
from analysis.word_definitions import define_new_words, make_meanings
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error

# 번역 앞부분(#303)을 알리는 최소 간격. 조각마다 알리면 Redis 소식과 화면 갱신이 너무 잦다.
PARTIAL_INTERVAL_SECONDS = 0.1


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


def _attempt(started):
    """작업 소식에 싣는 시도 식별자. 선점할 때마다 새로 쓰는 processing_started_at이다.

    세대 번호는 검수 사건으로도 올라 시도를 가르지 못한다. 구독한 뒤 다시 선점한 요청이 앞
    시도의 소식을 자기 것으로 받지 않게 한다.
    """
    return started.isoformat() if started else None


def _processing(analysis_id, started):
    """그 시도(started)로 처리 중인 분석 행. 그사이 다시 선점됐거나 끝났으면 비어 있다(#99)."""
    return SentenceAnalysis.objects.filter(
        pk=analysis_id,
        status=SentenceAnalysis.Status.PROCESSING,
        processing_started_at=started,
    )


def _fail(analysis_id, started, code):
    """그 시도(started)로 처리 중인 분석 행을 실패로 두고 알린다. 다음 요청이 다시 선점한다."""
    _processing(analysis_id, started).update(
        status=SentenceAnalysis.Status.FAILED, processing_translation_ko=None
    )
    sentence_hash = (
        SentenceAnalysis.objects.filter(pk=analysis_id)
        .values_list("sentence_hash", flat=True)
        .first()
    )
    if sentence_hash is not None:
        message = {"type": "failed", "error": code, "attempt": _attempt(started)}
        jobs.publish(sentence_hash, message)


def run_analysis(analysis_id, text, usage_id, started):
    """작업자가 실행하는 분석 LLM 작업(analysis.jobs). text는 요청이 정규화한 분석 텍스트,
    started는 선점한 시도다. 행을 읽고 쓰고 소식을 보낼 때 모두 이 시도를 기준으로 한다(#99).

    정규화는 두 번 적용하면 결과가 달라질 수 있어(공백을 지운 뒤 결합 탁점이 합쳐지는 등) 다시
    하지 않는다. 그러지 않으면 해시가 달라져 요청이 선점한 행을 찾지 못한다.
    """
    job = _job_record(analysis_id, usage_id, started)
    try:
        Worker(Sentence(text), started, job).run(analysis_id, usage_id)
    except BaseException:
        # 우리 코드의 버그와 작업 시간 초과(RQ가 작업 안에서 올린다)도 실패로 알린 뒤 그대로
        # 올린다. 기다리는 요청이 대기 상한까지 붙잡히거나 행이 처리 중에 남지 않게 한다.
        job.end("failed", AnalysisError.FAILED.code)
        _fail(analysis_id, started, AnalysisError.FAILED.code)
        raise
    finally:
        job.log()


def _job_record(analysis_id, usage_id, started):
    """작업 하나의 시간 기록(#216). 단계 시각은 작업 시작부터 잰다. 큐 대기는 요청이 선점한
    시각부터 작업 시작까지라 프로세스가 달라 벽시계로 잰다. worker는 실행한 작업자 프로세스다.
    """
    return timing.Record(
        "analysis_job",
        analysis_id=analysis_id,
        attempt=_attempt(started),
        request_id=usage_id,
        worker=f"{socket.gethostname()}:{os.getpid()}",
        queue_wait_s=round((timezone.now() - started).total_seconds(), 3) if started else None,
        translation_s=None,
        first_response_s=None,
        result=None,
        error=None,
    )


class Worker:
    """선점된 분석 행 하나의 LLM 분석과 저장.

    이 작업의 LLM 호출(분석·다시 묻기·예문 다시 쓰기)은 한 클라이언트(client)로 해서 요청 전체
    마감 시각을 함께 쓴다. usage는 선점한 요청의 사용 기록이다. 둘 다 run이 채운다. started는
    이 작업이 맡은 시도, job은 이 작업의 시간 기록이다.
    """

    def __init__(self, sentence, started, job):
        self.sentence = sentence
        self.started = started
        self.job = job
        self.client = self.usage = None

    def run(self, analysis_id, usage_id):
        """선점된 분석 행(analysis_id)을 분석한다. usage_id는 선점한 요청의 request 기록이다.

        저장에 성공하면 done, 실패하면 failed 소식을 보낸다. 그 밖의 예외는 run_analysis가 실패로
        알린다.
        """
        existing = self.sentence.existing
        if existing is None or existing.pk != analysis_id:
            raise RuntimeError(f"분석 텍스트의 해시가 분석 행과 다름: analysis_id={analysis_id}")
        # 세대 번호(Sentence가 읽음)를 읽은 뒤에 본다. 그 사이 다시 선점됐으면 여기서 걸러진다.
        if not _processing(analysis_id, self.started).exists():
            # 다시 선점된 뒤 큐에서 늦게 꺼낸 옛 작업이다. 새 시도의 행과 소식을 건드리지 않는다.
            self.job.end("skipped")
            return
        self.usage = RequestUsage.resume(usage_id, analysis_id)
        if limits.over_limit(self.usage.user):
            # 연결을 끊고 다시 보내기를 되풀이해 쌓인 작업이 하루 한도를 크게 넘기지 않게,
            # 시작할 때 다시 본다(#28, PR #155 리뷰).
            self.fail(analysis_id, AnalysisError.USAGE_LIMIT.code)
            return
        self.client = llm.get_client(self.usage.record_llm)
        try:
            self.work()
        except BusinessError as e:
            log_business_error(e)
            self.fail(analysis_id, e.error_code.code)
            return
        self.usage.succeed()
        self.job.end("done")
        self.publish({"type": "done"})

    def fail(self, analysis_id, code):
        self.job.end("failed", code)
        _fail(analysis_id, self.started, code)

    def work(self):
        """LLM 분석을 하고 저장한다. 번역을 검증하자마자 먼저 알리고, 판정 칸·단어 칸이 닫히면 그
        칸만 검증해 판정·고른 뜻을 알린 뒤(#204, #205), 문법·단어까지 검증해 저장한다. 실패하면
        BusinessError이고 어느 단계에서 실패해도 저장하지 않는다.
        """
        s = self.sentence
        translated = words_judged = False
        # 먼저 알린 판정. 알리지 않았으면 None
        span_answers = None
        result = None
        partial_at = -math.inf
        for kind, value in self.client.analyze_stream(
            s.key_text, s.tokens, s.llm_spans, s.decided_spans, s.llm_words, s.unknown
        ):
            if kind == "translation_partial":
                # 검증 전 앞부분이라 저장하지 않고 알리기만 한다. 늦게 붙은 요청은 다음 앞부분이나
                # 저장된 번역을 받는다.
                now = time.monotonic()
                if now - partial_at >= PARTIAL_INTERVAL_SECONDS:
                    partial_at = now
                    self.publish({"type": "translation_partial", "translation_ko": value})
            elif kind == "translation":
                _validate_translation(value, s.numbers)
                translated = True
                self.share_translation(value)
            elif kind == "spans":
                span_answers = self.early_span_answers(value) if translated and s.spans else None
                if span_answers is not None:
                    # 단어는 아직 고르지 않았다(None). 화면은 먼저 보낸 사전 단어를 그대로 둔다.
                    self.publish(
                        {
                            "type": "judged",
                            "spans": _judged_spans(s.spans, span_answers),
                            "word_spans": None,
                        }
                    )
            elif kind == "words":
                # judged는 화면의 문법도 통째로 바꾸므로, 판정을 먼저 알렸을 때(판정할 구간이 없을
                # 때 포함)만 그 판정과 함께 알린다.
                chosen = (
                    _validate_word_answers(value, s.ambiguous)
                    if translated and s.ambiguous and (span_answers is not None or not s.spans)
                    else None
                )
                if chosen is not None:
                    words_judged = True
                    self.publish(
                        {
                            "type": "judged",
                            "spans": _judged_spans(s.spans, span_answers or []),
                            "word_spans": s.word_spans(chosen),
                        }
                    )
            else:
                self.job.mark("first_response")
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
        if (s.ambiguous and not words_judged) or (s.spans and span_answers is None):
            self.publish(
                {
                    "type": "judged",
                    "spans": _judged_spans(s.spans, validated["spans"]),
                    "word_spans": stored_words,
                }
            )
        # 다시 묻기는 번역을 알린 뒤, 저장 트랜잭션 밖에서 한다.
        asked = self.ask_again(reask.prepare(s, validated))
        # 사전에 없던 단어는 저장 전에 2단계로 만들어 analysis에 함께 싣는다(#134). 꼭 해야 하는
        # 다시 묻기가 요청 마감을 먼저 쓰도록 그 뒤에 한다.
        defined = define_new_words(s, self.client, validated["new_words"], self.job_outdated)
        asked["words"] = {**asked["words"], **defined}
        stored_words = s.word_spans(asked["words"])
        self.save(asked)
        # 한국어 뜻은 저장한 뒤 만든다. 느리거나 실패해도 분석은 이미 저장돼 있고, 요청 마감을
        # 다시 묻기·예문 다시 쓰기보다 먼저 쓰지 않는다. 새 한국어 뜻은 done 뒤 analysis에 실린다.
        make_meanings(self.client, analysis_store._sense_ids(stored_words))

    def share_translation(self, translation):
        """검증한 번역을 먼저 저장하고 알린다. 늦게 붙은 요청은 저장된 번역을 읽는다."""
        _processing(self.sentence.existing.pk, self.started).update(
            processing_translation_ko=translation
        )
        self.job.mark("translation")
        self.publish({"type": "translation", "translation_ko": translation})

    def publish(self, message):
        """이 시도의 작업 소식을 보낸다."""
        s = self.sentence
        jobs.publish(s.sentence_hash, {**message, "attempt": _attempt(self.started)})

    def early_span_answers(self, answers):
        """응답 도중 닫힌 판정 칸을 응답 전체와 같은 규칙으로 검증한 판정. 틀렸거나 새 용법 글이
        문장 전체를 인용했으면 None이다(알리지 않고, 응답 전체 검증에서 실패한다).
        """
        s = self.sentence
        try:
            checked = _validate_span_answers(answers, s.spans)
        except SpanAnswersRejected:
            return None
        texts = [
            new_usage[field]
            for _, _, new_usage in checked
            if new_usage is not None
            for field in ("usage_name", "explanation_ko")
        ]
        return None if _quotes_whole_sentence(texts, s.key_text, s.content_tokens) else checked

    def job_outdated(self):
        """이 작업의 결과가 버려질 것인가. 시작한 뒤 세대 번호가 올랐으면 저장하지 않는다(save)."""
        s = self.sentence
        return (
            SentenceAnalysis.objects.filter(pk=s.existing.pk)
            .exclude(generation=s.started_generation)
            .exists()
        )

    def ask_again(self, validated):
        return reask.ask_again(self.sentence, self.client, validated, self.job_outdated)

    def save(self, validated, final=False):
        """검증한 결과를 공용 캐시에 저장한다.

        저장하는 사이 다른 요청이 같은 조건의 패턴을 먼저 등록했으면, 저장을 되돌리고 그 패턴의
        용법 목록으로 다시 물은 뒤 한 번만 다시 저장한다. 분석하는 사이 영향 범위가 바뀌었거나
        다른 쓰기가 같은 구간을 먼저 넣었으면 저장하지 않고 ANALYSIS:FAILED다. 다음 요청이 다시
        선점해 분석한다(#98).
        """
        s = self.sentence
        # 다시 물어 받은 새 용법도 공용 테이블에 들어가므로 다시 본다.
        reject_quotes(validated, s)
        _check_examples(
            validated, self.client, s.key_text, s.content_tokens, s.key_span, self.job_outdated
        )
        try:
            outdated = analysis_store.store(s, validated, final)
        except _PatternTaken:
            # LLM 호출은 트랜잭션 밖에서 한다.
            self.save(self.ask_again(validated), final=True)
            return
        if outdated:
            raise BusinessError(AnalysisError.FAILED, "분석하는 사이 영향 범위가 바뀜")
