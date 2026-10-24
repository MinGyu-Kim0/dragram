import hashlib
import json
import logging
from itertools import chain
from types import SimpleNamespace

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import F
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from accounts.tokens import ExtensionTokenAuthentication
from analysis import jobs, llm, patterns, words
from analysis.answers import (
    _NEW_PATTERN_TEXTS,
    FIRST_VERDICTS,
    RECHECK_VERDICTS,
    _is_text,
    _quotes_whole_sentence,
    _validate,
    _validate_recheck_answers,
    _validate_translation,
)
from analysis.examples import _check_examples
from analysis.models import (
    GrammarPattern,
    GrammarUsage,
    ReviewStatus,
    SentenceAnalysis,
    SpanMatch,
    UsageLog,
)
from analysis.morphology import morphemes
from analysis.normalize import (
    NORMALIZE_VERSION,
    analysis_text,
    has_all_placeholders,
    key_pieces,
    restore_numbers,
)
from analysis.positions import key_offsets, to_analysis, to_key, to_original, utf16_offsets
from analysis.presenter import (
    _grammar_entries,
    _grammar_item,
    _grammar_response,
    _review_status,
    _ruby_response,
    _with_parts,
    _words_response,
)
from analysis.ruby import ruby_pieces
from analysis.sentence import (
    _NON_WORD_POS,
    _approved_rules,
    _closed_usage,
    _is_fresh,
    _llm_spans,
    _numbers_before_particle,
    _pattern_statuses,
    _rule_usage,
)
from analysis.span_rows import (
    _basis_changed,
    _is_place_conflict,
    _PatternTaken,
    _stored_keys,
    _usage_owner,
)
from analysis.usage import RequestUsage
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error

logger = logging.getLogger(__name__)


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
    # 만든 패턴이 원래 문장의 그 자리에 다시 걸려야 저장한다.
    if not patterns.matches_at(conditions, morphs, ids[0]):
        return None
    return conditions


def _sense_ids(word_spans):
    """word_spans의 뜻 ID를 중복 없이 모은다."""
    return sorted({span["sense_id"] for span in word_spans})


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


# 응답은 줄 단위 JSON(한 줄에 이벤트 하나)이다(#27).
# translation(번역, 루비) → analysis(번역, 문법, 단어) 순서다. 형태소 분석 등 응답을 시작하기 전의
# 실패는 다른 API 오류처럼 상태 코드로, 작업자의 LLM 작업 실패는 error 이벤트로 알린다(#98).
_NDJSON = "application/x-ndjson"


def _ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


# 확장 토큰으로 로그인한 사용자만 쓴다. 토큰이 없거나 쓸 수 없으면 형태소 분석·LLM 전에
# AUTH:LOGIN_REQUIRED로 거부한다(#109).
@api_view(["POST"])
@authentication_classes([ExtensionTokenAuthentication])
@permission_classes([])
def analyze(request):
    sentence = request.data.get("text") if isinstance(request.data, dict) else None
    if not _is_text(sentence):
        raise BusinessError(AnalysisError.TEXT_REQUIRED, "분석할 문장이 없음")
    return _pipeline(sentence).respond(request.user)


def run_analysis(analysis_id, text, usage_id):
    """작업자가 실행하는 분석 LLM 작업(analysis.jobs). text는 분석 텍스트다."""
    started = (
        SentenceAnalysis.objects.filter(pk=analysis_id)
        .values_list("processing_started_at", flat=True)
        .first()
    )
    try:
        _pipeline(text, normalized=True).run(analysis_id, usage_id)
    except BaseException:
        # 우리 코드의 버그와 작업 시간 초과(RQ가 작업 안에서 올린다)도 실패로 알린 뒤 그대로
        # 올린다. 기다리는 요청이 대기 상한까지 붙잡히거나 행이 처리 중에 남지 않게 한다.
        _fail(analysis_id, started, AnalysisError.FAILED.code)
        raise


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


# 요청이 작업 소식을 기다리는 상한. 작업 시간 제한(jobs.JOB_TIMEOUT_SECONDS)보다 길고, 큐에 넣은
# 때부터 세므로 큐 대기도 포함한다. 넘으면 error 이벤트로 닫고, 작업은 계속된다(ADR 0005).
WAIT_SECONDS = 130


def _in_thread(events):
    """동기 이벤트 생성기를 비동기 스트림으로 흘려보낸다(재매칭).

    다음 이벤트는 요청 스레드가 아닌 스레드에서 만든다. ASGI에서는 동기 코드가 한 스레드에서 돌아
    LLM을 기다리는 동안 다른 요청까지 막기 때문이다. 이벤트 사이에 걸친 트랜잭션이 없어 이벤트마다
    그 스레드의 DB 연결을 정리한다.
    """
    inline = settings.ANALYSIS_INLINE

    def step():
        try:
            return next(events, None)
        finally:
            if not inline:
                close_old_connections()

    async def stream():
        while (event := await sync_to_async(step, thread_sensitive=inline)()) is not None:
            yield _ndjson(event)

    return stream()


def _pipeline(sentence, normalized=False):
    """원문 하나의 분석. 요청 쪽은 respond, 작업자는 run을 쓴다.

    작업자는 요청이 정규화한 분석 텍스트를 받는다(normalized). 정규화는 두 번 적용하면 결과가
    달라질 수 있어(공백을 지운 뒤 결합 탁점이 합쳐지는 등) 다시 하지 않는다. 그러지 않으면 해시가
    달라져 요청이 선점한 행을 찾지 못한다.
    """
    if normalized:
        text_to_analyze, origins = sentence, [(i, i + 1) for i in range(len(sentence))]
    else:
        text_to_analyze, origins = analysis_text(sentence)
    if not text_to_analyze:
        raise BusinessError(AnalysisError.TEXT_REQUIRED, "정규화 후 빈 문장")
    pieces, numbers = key_pieces(text_to_analyze)
    key_text = "".join(pieces)
    sentence_hash = hashlib.sha256(key_text.encode()).hexdigest()

    # 형태소 분석은 숫자가 그대로인 분석 텍스트로 한다. 숫자 뒤 조사 교정에 쓰므로 캐시를
    # 재사용할 때도 한다. 원문은 로그에 남기지 않는다.
    morphs = morphemes(text_to_analyze)
    particle_numbers = _numbers_before_particle(text_to_analyze, morphs)

    offsets = key_offsets(pieces)
    utf16 = utf16_offsets(sentence)
    # 저장된 단어 위치(키 텍스트 구간) → 이 요청의 형태소
    token_at = {to_key(offsets, m.begin, m.end): m for m in morphs}

    def restore(text):
        return restore_numbers(text, numbers, particle_numbers)

    # 루비는 SudachiPy 읽기라 LLM·캐시와 상관없이 요청마다 이 원문 기준으로 계산한다.
    ruby = _ruby_response(ruby_pieces(text_to_analyze, morphs), origins, utf16)

    def translation_event(translation):
        return {"type": "translation", "translation_ko": restore(translation), "ruby": ruby}

    def analysis_event(saved):
        # 동시에 저장된 다른 요청의 결과를 쓸 수 있어, 문법·단어와 짝인 번역을 함께 싣는다.
        return {
            "type": "analysis",
            "translation_ko": restore(saved.translation_ko),
            "grammar": _grammar_response(saved, offsets, origins, utf16, restore),
            "words": _words_response(
                saved.word_spans, text_to_analyze, token_at, offsets, origins, utf16
            ),
        }

    # 단어 칸을 받기 전에 저장된 행(word_spans가 NULL)과 stale 행은 다시 분석한다.
    existing = SentenceAnalysis.objects.filter(sentence_hash=sentence_hash).first()
    cached = existing if existing is not None and _is_fresh(existing) else None
    # 다시 분석하는 동안 영향 범위의 패턴·용법 상태가 바뀌면 이 값이 올라 저장하지 않는다.
    started_generation = existing.generation if existing is not None else 0
    # 분석에는 매칭(candidate_spans) 직전에 읽은 패턴 세트 버전을 기록한다. 그 뒤에 활성화된
    # 패턴은 다음 조회가 다시 매칭해 찾는다. 캐시 분석의 버전이 이보다 낮으면 다시 매칭한다(#41).
    matcher_version = patterns.pattern_set_version()
    # 작업자가 쓰는 LLM 클라이언트와 선점한 요청의 사용 기록(run이 채운다)
    client = usage = None

    # LLM에는 키 텍스트 기준 표층형을 보내 원문 숫자가 가지 않게 한다.
    tokens = [{"id": i, "surface": "".join(pieces[m.begin : m.end])} for i, m in enumerate(morphs)]

    def overlaps_number(token):
        # 숫자열은 자리표시자 조각과 빈 조각(뒤쪽 숫자)으로 이뤄진다.
        m = morphs[token]
        return any(piece == "" or "⟨N" in piece for piece in pieces[m.begin : m.end])

    def is_vocabulary(token):
        # 숫자는 학습할 단어가 아니고, 숫자열과 겹치는 토큰(X12의 X1, 2)은 LLM이 사전형에
        # 숫자를 지어내면 숫자만 다른 문장에 잘못 재사용된다.
        return morphs[token].pos not in _NON_WORD_POS and not overlaps_number(token)

    # 등록된 패턴에 걸린 구간과 후보 용법. LLM은 서버가 매긴 구간·후보 ID로만 답한다.
    # 승인된 용법 완결 패턴의 구간(#39)과 승인된 판별 규칙으로 정해지는 구간(#55)은 LLM 없이
    # 확정하고, 나머지만 후보로 묻는다. 확정 구간은 LLM이 새 구문으로 다시 내지 않도록 알리기만
    # 한다.
    matched = patterns.candidate_spans(morphs)
    rules = _approved_rules(matched)
    # (구간, 후보 ID, 용법, 판별 규칙(용법 완결 확정이면 None))
    closed_spans, spans = [], []
    for span in matched:
        closed = _closed_usage(span)
        if closed is not None:
            closed_spans.append((span, *closed, None))
        elif (by_rule := _rule_usage(span, morphs, rules)) is not None:
            closed_spans.append((span, *by_rule))
        else:
            spans.append(span)
    llm_spans = _llm_spans(spans)
    decided_spans = [
        {"start_token_id": span.start_token, "end_token_id": span.end_token, "name": usage.name}
        for span, _, usage, _ in closed_spans
    ]
    content_tokens = sum(m.pos not in {"補助記号", "空白"} for m in morphs)

    def key_span(start_token, end_token):
        return to_key(offsets, morphs[start_token].begin, morphs[end_token].end)

    def prepare(validated):
        """새 구문마다 형태소 조건을 만든다. 패턴 생성 규칙을 어겼으면 None이다. 같은 자리에서
        이미 판정한 후보 구간이나 앞서 낸 새 구문과 패턴이 같은 제안은 같은 구간이므로 뺀다.
        판정할 후보 구간도 함께 둔다.
        """
        # morpheme_key가 같으면 토큰 수도 같으므로 (key, 시작 토큰)이 같으면 같은 구간이다.
        placed = {(span.pattern.morpheme_key, span.start_token) for span in matched}
        new_patterns = []
        for proposal in validated["new_patterns"]:
            conditions = _new_pattern_conditions(proposal["tokens"], morphs, overlaps_number)
            if conditions is not None:
                place = (patterns.morpheme_key(conditions), proposal["tokens"][0][0])
                if place in placed:
                    continue
                placed.add(place)
            new_patterns.append({**proposal, "conditions": conditions, "existing": None})
        return {**validated, "new_patterns": new_patterns, "span_list": spans}

    def job_outdated():
        """이 작업의 결과가 버려질 것인가. 시작한 뒤 세대 번호가 올랐으면 저장하지 않는다(save)."""
        return (
            SentenceAnalysis.objects.filter(pk=existing.pk)
            .exclude(generation=started_generation)
            .exists()
        )

    def ask_again(validated):
        """첫 응답의 해석 갈림·미확정 구간과, 형태소 조건이 같은 패턴이 이미 있는 새 구문을 한
        요청으로 다시 묻는다(#40). 이 호출이 마지막이다.

        같은 조건의 새 구문은 새 용법을 버리고 그 패턴의 기존 용법 목록으로 묻고, 물은 구간은
        판정할 후보 구간으로 옮긴다. 반려된 패턴이면 묻지 않고 미발견으로 남긴다. 해석 갈림·
        미확정 구간은 한 번만 묻는다(_PatternTaken 뒤 다시 부를 때는 빼고, 그 답은 다시 묻지
        않는다). 그 구간의 주 해석이 바뀌었을 때만 다시 받은 번역으로 바꾼다.
        """
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
            {"start_token_id": span.start_token, "end_token_id": span.end_token, "name": usage.name}
            for span, (state, usage, _) in zip(
                validated["span_list"], validated["spans"], strict=True
            )
            if state == SpanMatch.State.DECIDED
        ]
        result = client.judge_spans(
            key_text,
            tokens,
            validated["translation_ko"],
            decided_spans + decided,
            llm_spans[: len(recheck)],
            llm_spans[len(recheck) :],
        )
        if not isinstance(result, dict):
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 다시 묻기")
        checked = _validate_recheck_answers(
            result.get("spans"),
            recheck_spans + asked,
            [RECHECK_VERDICTS] * len(recheck) + [FIRST_VERDICTS] * len(asked),
            numbers,
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
            if not _is_text(translation) or not has_all_placeholders(translation, numbers):
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

    def closed_rows(saved, closed):
        """LLM 없이 확정한 구간(구간, 후보 ID, 용법, 판별 규칙)들의 구간 매칭."""
        rows = []
        for span, candidate_id, usage, rule in closed:
            start, end = key_span(span.start_token, span.end_token)
            rows.append(
                SpanMatch(
                    analysis=saved,
                    pattern=span.pattern,
                    usage=usage,
                    start_offset=start,
                    end_offset=end,
                    state=SpanMatch.State.DECIDED,
                    decided_by=(
                        SpanMatch.DecidedBy.RULE if rule else SpanMatch.DecidedBy.SINGLE_USAGE
                    ),
                    rule=rule,
                    candidates=[{"candidate_id": candidate_id, "usage_id": usage.id}],
                )
            )
        return rows

    def judged_rows(saved, span_list, answers, alternatives):
        """LLM이 판정한 후보 구간들의 구간 매칭. 미발견 구간의 새 용법은 이때 더한다.

        (구간 매칭들, 매칭 자격을 새로 얻은 패턴이 있는가)를 돌려준다. 자격을 얻었으면 호출하는
        쪽이 분석 행을 잠그기 전에 패턴 세트 버전을 올린다. alternatives는 해석 갈림 구간의
        {순번: [(대안 용법, 대안 번역)]}이다.
        """
        judged = list(zip(span_list, answers, strict=True))
        # 기존 용법으로 설명되지 않는 구간은 같은 패턴 아래 새 용법을 더한다. 동시 요청이 같은
        # 이름의 용법을 서로 다른 순서로 더하면 유일성 대기가 엇갈려 교착이 나므로 (패턴, 이름)
        # 순서로 더한다. 이 응답에서 이미 더한 (패턴, 이름)이면 그 용법을 함께 쓴다.
        # 연결된 회화체 구간의 새 용법은 원형 아래에 더하고, 이름과 순서도 원형 기준이다(#63).
        additions = sorted(
            (_usage_owner(span.pattern).morpheme_key, new_usage["usage_name"], index)
            for index, (span, (_, _, new_usage)) in enumerate(judged)
            if new_usage is not None
        )
        # 새 용법을 더할 패턴들(과 그 회화체들)을 처음에 한 번에 잠근다. 하나씩 잠그면 연결·해제나
        # 다른 분석과 잠금 순서가 엇갈릴 수 있다(#63).
        if additions:
            patterns.lock_families(
                *(_usage_owner(judged[index][0].pattern) for *_, index in additions)
            )
        # 용법 예문은 같은 (패턴, 이름)의 답 중 검사를 통과한 첫 예문이다(check_examples).
        usage_examples = {}
        for _, name, index in additions:
            span, (_, _, new_usage) = judged[index]
            owner = _usage_owner(span.pattern)
            if usage_examples.get((owner.id, name)) is None:
                usage_examples[owner.id, name] = new_usage["checked_example"]
        added, new_usages = {}, {}
        activated = False
        for _, name, index in additions:
            span, (_, _, new_usage) = judged[index]
            owner = _usage_owner(span.pattern)
            # 같은 원형을 가리키는 회화체 구간들은 같은 새 용법을 함께 쓴다. 나머지 구간의 연결
            # 상태는 저장 직전에 함께 본다(_links_changed).
            if (owner.id, name) not in added:
                added[owner.id, name], matchable = patterns.add_usage(
                    owner,
                    name,
                    new_usage["explanation_ko"],
                    usage_examples[owner.id, name],
                    matched=span.pattern,
                )
                activated |= matchable
            new_usages[index] = added[owner.id, name]
        rows = []
        for index, (span, (state, usage, new_usage)) in enumerate(judged):
            start, end = key_span(span.start_token, span.end_token)
            if new_usage is not None:
                usage = new_usages[index]
                if usage is not None:
                    state = SpanMatch.State.DECIDED
            alts = None
            if state == SpanMatch.State.DIVERGENT:
                alts = [
                    {"usage_id": alt.id, "translation_ko": translation}
                    for alt, translation in alternatives[index]
                ]
            rows.append(
                SpanMatch(
                    analysis=saved,
                    pattern=span.pattern,
                    usage=usage,
                    start_offset=start,
                    end_offset=end,
                    state=state,
                    decided_by=SpanMatch.DecidedBy.LLM,
                    candidates=[
                        {"candidate_id": candidate_id, "usage_id": u.id}
                        for candidate_id, u in span.candidates
                    ],
                    alternatives=alts,
                )
            )
        return rows, activated

    def span_matches(saved, validated, final):
        """판정한 후보 구간과 새 구문을 구간 매칭으로 만든다. 새 구문은 이때 등록한다. 넣을 구간
        매칭을 돌려주고, 호출하는 쪽이 분석 행을 잠근 뒤 넣는다.

        패턴 생성 규칙을 어긴 새 구문은 미발견으로 남겨 보이지 않는다. 그사이 다른 요청이 같은
        조건의 패턴을 먼저 등록했으면 _PatternTaken을 던져 다시 묻게 한다(final이면 미발견).
        """
        # 다른 요청이 먼저 저장해 다시 묻기를 건너뛰었는데, 그 행이 저장 전에 stale이 되어 이
        # 결과로 다시 채우게 된 경우다. 다시 묻지 않은 해석 갈림·미확정은 저장하지 않는다.
        if not validated.get("rechecked") and any(
            state in (SpanMatch.State.DIVERGENT, SpanMatch.State.UNRESOLVED)
            for state, _, _ in validated["spans"]
        ):
            raise BusinessError(AnalysisError.FAILED, "다시 묻지 않은 해석 갈림·미확정 구간")
        rows, activated = judged_rows(
            saved, validated["span_list"], validated["spans"], validated.get("alternatives", {})
        )
        rows = closed_rows(saved, closed_spans) + rows

        # 동시 요청이 같은 패턴들을 서로 다른 순서로 등록하면 morpheme_key 유일성 대기가
        # 엇갈려 교착이 나므로, 등록은 morpheme_key 순서로 한다.
        def order(proposal):
            conditions = proposal["conditions"]
            return patterns.morpheme_key(conditions) if conditions is not None else ""

        # 같은 조건이 이 응답에서 두 번 나오면 패턴은 한 번만 등록한다. 뒤 자리는 용법 이름이
        # 같으면 그 용법을 함께 쓰고, 다르면 같은 패턴 아래 새 용법으로 더한다. 이 패턴은 이번
        # 트랜잭션에서 만들어 다른 요청이 용법을 더할 수 없으므로 순서를 맞출 필요가 없다.
        registered = {}
        proposals = sorted(validated["new_patterns"], key=order)
        # 같은 조건의 제안 중 검사를 통과한 첫 예문(check_examples)이 패턴의 활성화 근거가
        # 되고, 같은 조건·같은 용법 이름의 제안 중 통과한 첫 예문이 그 용법의 예문이 된다(다른
        # 용법의 예문은 용법 예문으로 쓰지 않는다).
        examples = [p.get("checked_example") for p in proposals]
        test_examples, usage_examples = {}, {}
        for proposal, example in zip(proposals, examples, strict=True):
            if example is not None:
                test_examples.setdefault(order(proposal), example)
                usage_examples.setdefault((order(proposal), proposal["usage_name"]), example)
        for proposal in proposals:
            example = usage_examples.get((order(proposal), proposal["usage_name"]))
            ids = [token for token, _ in proposal["tokens"]]
            start, end = key_span(min(ids), max(ids))
            pattern, usage = proposal["existing"], None
            if order(proposal) in registered:
                pattern, usages = registered[order(proposal)]
                name = proposal["usage_name"]
                if name not in usages and usages:
                    usages[name], _ = patterns.add_usage(
                        pattern, name, proposal["explanation_ko"], example
                    )
                usage = usages.get(name)
            elif pattern is None and proposal["conditions"] is not None:
                pattern, usage = patterns.register(
                    proposal["conditions"],
                    proposal["pattern_name"],
                    proposal["usage_name"],
                    proposal["explanation_ko"],
                    example,
                    test_examples.get(order(proposal)),
                )
                if usage is None and not final:
                    raise _PatternTaken
                registered[order(proposal)] = (
                    pattern,
                    {proposal["usage_name"]: usage} if usage else {},
                )
                activated |= usage is not None and pattern.is_active
            rows.append(
                SpanMatch(
                    analysis=saved,
                    pattern=pattern,
                    usage=usage,
                    start_offset=start,
                    end_offset=end,
                    state=SpanMatch.State.DECIDED if usage else SpanMatch.State.UNFOUND,
                    decided_by=SpanMatch.DecidedBy.LLM,
                )
            )
        if activated:
            # 버전 행은 등록을 모두 마친 뒤 마지막에 잠근다(잠근 채 다른 패턴을 기다리지 않게).
            patterns.raise_pattern_set_version()
        return rows

    def reject_quotes(validated):
        """LLM이 쓴 글이 문장 전체를 인용했으면 ANALYSIS:FAILED다."""
        llm_texts = [
            item[field] for item in validated["new_patterns"] for field in _NEW_PATTERN_TEXTS
        ]
        llm_texts += [
            new_usage[field]
            for _, _, new_usage in validated["spans"]
            if new_usage is not None
            for field in ("usage_name", "explanation_ko")
        ]
        if _quotes_whole_sentence(llm_texts, key_text, content_tokens):
            # 이 글들은 공용 테이블에 들어가므로 원문을 통째로 옮긴 결과는 저장하지 않는다.
            raise BusinessError(AnalysisError.FAILED, "LLM이 쓴 글이 문장 전체를 인용함")

    def save(validated, final=False):
        """검증한 결과를 공용 캐시에 저장한다.

        저장하는 사이 다른 요청이 같은 조건의 패턴을 먼저 등록했으면, 저장을 되돌리고 그 패턴의
        용법 목록으로 다시 물은 뒤 한 번만 다시 저장한다. 분석하는 사이 영향 범위가 바뀌었으면
        저장하지 않고 ANALYSIS:FAILED다. 다음 요청이 다시 선점해 분석한다(#98).
        """
        # 다시 물어 받은 새 용법도 공용 테이블에 들어가므로 다시 본다.
        reject_quotes(validated)
        _check_examples(validated, client, key_text, content_tokens, key_span, job_outdated)
        stored_words = word_spans(validated["words"])

        try:
            with transaction.atomic():
                outdated = save_once(validated, stored_words, final)
                if outdated:
                    transaction.set_rollback(True)
        except _PatternTaken:
            # LLM 호출은 트랜잭션 밖에서 한다.
            save(ask_again(validated), final=True)
            return
        if outdated:
            raise BusinessError(AnalysisError.FAILED, "분석하는 사이 영향 범위가 바뀜")

    def save_once(validated, stored_words, final):
        """선점한 분석 행을 이번 결과로 통째로 바꾸고 완료로 둔다. 시작 뒤 세대 번호나 판정 근거가
        바뀌었으면 참이다(호출하는 쪽이 되돌린다). 호출하는 쪽이 트랜잭션을 연다.

        상태 전이(analysis.review)가 패턴 → 패턴 세트 버전 → 분석 순서로 잠그므로, 분석 행은 패턴
        쪽을 다 쓴 뒤 잠근다. 구간은 분석 행을 잠근 뒤 지우고 넣는다. 구간을 쓰는 모든 경로가 이
        순서라 같은 구간이 겹쳐 들어가지 않는다(#41).
        """
        patterns.lock_links()
        try:
            with transaction.atomic():
                rows = span_matches(existing, validated, final)
                locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=existing.pk)
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
        locked.matcher_version = max(locked.matcher_version, matcher_version)
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
        return locked.generation != started_generation or _basis_changed(rows, rules)

    def closed_grammar():
        """LLM 없이 확정한 구간의 응답 항목(원문 순서)."""
        grammar = []
        for span, _, usage, _ in sorted(
            closed_spans, key=lambda c: (c[0].start_token, c[0].end_token)
        ):
            start, end = key_span(span.start_token, span.end_token)
            grammar.append(_grammar_item(span.pattern, usage, start, end, offsets, origins, utf16))
        return grammar

    def checking(span_list):
        """판별 대상 구간의 원문 위치와 후보 용법의 이름·검수 상태(원문 순서). 후보 이름도 LLM이
        만든 지식이라 미검수면 미검수로 보인다(불변식). 반려된 용법은 후보에 없다.
        """
        items = []
        for span in sorted(span_list, key=lambda span: (span.start_token, span.end_token)):
            key_start, key_end = key_span(span.start_token, span.end_token)
            start, end = to_original(origins, utf16, *to_analysis(offsets, key_start, key_end))
            candidates = [
                {"name": usage.name, "review_status": _review_status(span.pattern, usage)}
                for _, usage in span.candidates
            ]
            items.append({"start": start, "end": end, "candidates": candidates})
        return items

    def early_events():
        """LLM을 기다리기 전에 DB만으로 보낼 이벤트.

        stale 행의 옛 결과는 다시 분석하는 동안 '재분석 중'으로 보이도록 먼저 보낸다(#60). 저장된
        결과를 그대로 내보내지 않고 analysis 이벤트와 같은 경로로 만들어, 반려된 구간은 빠지고 검수
        상태는 지금 지식 상태로 다시 계산된다. 이어서 확정 구간과 판별 대상 구간(화면의 확인 중),
        사전에서 찾은 단어를 보낸다(#39, #44, #96).
        """
        events = []
        if existing is not None and existing.word_spans is not None:
            events.append({**analysis_event(existing), "type": "previous", "ruby": ruby})
        early_words = sentence_words()
        if closed_spans or spans or early_words:
            events.append(
                {
                    "type": "grammar",
                    "grammar": closed_grammar(),
                    "checking": checking(spans),
                    "words": early_words,
                }
            )
        return events

    def claim(user):
        """이 문장의 LLM 작업을 선점한다. 구독한 뒤에 부른다(ADR 0005).

        (상태, 분석 행, 사용 기록)이다. 상태는 claimed(이 요청이 선점해 작업을 넣음),
        processing(다른 요청의 작업을 기다림), saved(그사이 다른 요청의 작업이 저장을 마침)다.
        처리 중이 아니고 다시 분석해야 하는 행만 조건부 UPDATE로 선점하고, 선점할 때마다 세대
        번호를 올린다. 새 문장은 처리 중 행을 먼저 만들어, 실패한 시도의 LLM 사용 기록도 그 행에
        잇는다.
        """
        processing = SentenceAnalysis.Status.PROCESSING
        row, claimed = SentenceAnalysis.objects.get_or_create(
            sentence_hash=sentence_hash,
            defaults={
                "normalize_version": NORMALIZE_VERSION,
                "normalized_length": len(key_text),
                "status": processing,
                "processing_started_at": timezone.now(),
            },
        )
        if not claimed:
            claimed = (
                SentenceAnalysis.objects.filter(pk=row.pk)
                .exclude(status=processing)
                .exclude(word_spans__isnull=False, is_stale=False)
                .update(
                    status=processing,
                    processing_started_at=timezone.now(),
                    generation=F("generation") + 1,
                    processing_translation_ko=None,
                )
            ) == 1
            row.refresh_from_db()
        if not claimed and _is_fresh(row):
            return "saved", row, RequestUsage.start(UsageLog.Path.CACHE, user, row.pk, True)
        usage = RequestUsage.start(UsageLog.Path.LLM, user, row.pk)
        if claimed:
            try:
                jobs.enqueue_analysis(row.pk, text_to_analyze, usage.id)
            except BaseException:
                # 큐에 넣지 못했으면 선점을 풀어, 다음 요청이 처리 중 행에 붙잡히지 않게 한다.
                _fail(row.pk, row.processing_started_at, AnalysisError.FAILED.code)
                raise
        return "claimed" if claimed else "processing", row, usage

    def saved_events(row, translated):
        """작업이 저장한 행의 이벤트. 번역을 아직 보내지 않았으면 함께 보낸다."""
        events = [] if translated else [translation_event(row.translation_ko)]
        return [*events, analysis_event(row)]

    async def llm_stream(user, early):
        """LLM 작업을 기다리는 요청의 이벤트(ADR 0005).

        DB만으로 정해지는 이벤트를 먼저 보내고, 작업 소식을 구독한 뒤 선점하거나 처리 중인 작업에
        붙는다. 번역 소식이 오면 번역을, 저장 소식이 오면 저장된 행으로 만든 analysis를 보낸다.
        늦게 붙은 요청은 작업이 먼저 저장한 번역부터 보낸다. 실패 소식이나 대기 상한이면 error다.
        """
        async with jobs.listen(sentence_hash) as pubsub:
            for event in early:
                yield _ndjson(event)
            state, row, request_usage = await sync_to_async(claim)(user)
            if state == "saved":
                for event in await sync_to_async(saved_events)(row, False):
                    yield _ndjson(event)
                return
            translated = state == "processing" and row.processing_translation_ko is not None
            if translated:
                yield _ndjson(translation_event(row.processing_translation_ko))
            error = AnalysisError.FAILED.code
            attempt = _attempt(row.processing_started_at)
            async for message in jobs.messages(pubsub, WAIT_SECONDS):
                if message.get("attempt") != attempt:
                    continue
                if message["type"] == "translation":
                    if not translated:
                        translated = True
                        yield _ndjson(translation_event(message["translation_ko"]))
                    continue
                if message["type"] == "done":
                    row = await sync_to_async(SentenceAnalysis.objects.get)(pk=row.pk)
                    if row.word_spans is not None:
                        for event in await sync_to_async(saved_events)(row, translated):
                            yield _ndjson(event)
                        await sync_to_async(request_usage.succeed)()
                        return
                else:
                    error = message["error"]
                break
            else:
                logger.warning("분석 작업 대기 시간 초과: analysis_id=%s", row.pk)
            yield _ndjson({"type": "error", "error": error})

    def share_translation(translation):
        """검증한 번역을 먼저 저장하고 알린다. 늦게 붙은 요청은 저장된 번역을 읽는다."""
        SentenceAnalysis.objects.filter(
            pk=existing.pk, status=SentenceAnalysis.Status.PROCESSING
        ).update(processing_translation_ko=translation)
        publish({"type": "translation", "translation_ko": translation})

    def publish(message):
        """이 시도의 작업 소식을 보낸다."""
        jobs.publish(
            sentence_hash, {**message, "attempt": _attempt(existing.processing_started_at)}
        )

    def work():
        """작업자에서 LLM 분석을 하고 저장한다. 번역을 검증하자마자 먼저 알리고, 문법·단어까지
        검증해 저장한다. 실패하면 BusinessError이고 어느 단계에서 실패해도 저장하지 않는다.
        """
        translated = False
        result = None
        for kind, value in client.analyze_stream(
            key_text, tokens, llm_spans, decided_spans, llm_words
        ):
            if kind == "translation":
                _validate_translation(value, numbers)
                translated = True
                share_translation(value)
            else:
                result = value
        validated = _validate(result, numbers, len(morphs), spans, ambiguous)
        if not translated:
            share_translation(validated["translation_ko"])
        # 거부될 응답이면 다시 묻지 않는다.
        reject_quotes(validated)
        # 다시 묻기는 번역을 알린 뒤, 저장 트랜잭션 밖에서 한다.
        save(ask_again(prepare(validated)))

    def run(analysis_id, usage_id):
        """작업자: 선점된 분석 행(analysis_id)을 분석한다. usage_id는 선점한 요청의 request
        기록이다.

        저장에 성공하면 done, 실패하면 failed 소식을 보낸다. 그 밖의 예외는 run_analysis가 실패로
        알린다.
        """
        nonlocal client, usage
        if existing is None or existing.pk != analysis_id:
            raise RuntimeError(f"분석 텍스트의 해시가 분석 행과 다름: analysis_id={analysis_id}")
        usage = RequestUsage(UsageLog.objects.get(pk=usage_id))
        client = llm.get_client(usage.record_llm)
        try:
            work()
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
        usage.succeed()
        publish({"type": "done"})

    def span_key(span):
        """구간의 열쇠: (패턴 ID, 키 텍스트 start, end)."""
        return (span.pattern.id, *key_span(span.start_token, span.end_token))

    def rematch_grammar(analysis, new_closed):
        """저장 구간(조회 규칙 적용)에, 아직 저장되지 않은 새 DB 확정 구간을 더한 문법.
        _grammar_entries와 같은 (항목, show_parts) 목록(원문 순서)이다.

        확정 구간의 패턴·용법 상태는 DB에서 다시 읽어 반려됐으면 뺀다. 매칭할 때 읽은 상태라
        그사이 반려됐을 수 있다.
        """
        grammar = _grammar_entries(analysis, offsets, origins, utf16, restore)
        stored_keys = _stored_keys(analysis)
        usages = GrammarUsage.objects.select_related("pattern").in_bulk(
            [usage.id for _, _, usage, _ in new_closed]
        )
        matched = GrammarPattern.objects.select_related("variant_of").in_bulk(
            [span.pattern.id for span, *_ in new_closed]
        )
        for span, _, usage, _ in new_closed:
            current = usages.get(usage.id)
            if span_key(span) in stored_keys or current is None:
                continue
            start, end = key_span(span.start_token, span.end_token)
            pattern = matched[span.pattern.id]
            item = _grammar_item(pattern, current, start, end, offsets, origins, utf16)
            if item is not None:
                grammar.append((item, pattern.show_parts))
        return sorted(grammar, key=lambda entry: (entry[0]["start"], entry[0]["end"]))

    def rematch_fallback(new_closed):
        """다시 매칭한 결과를 저장하지 못했을 때의 analysis 이벤트.

        분석 행을 잠가 행과 구간을 한 시점에서 다시 읽는다(구간을 쓰는 모든 경로가 분석 행을
        잠근 뒤 커밋한다). 시작 때 읽은 행은 쓰지 않는다. 오래 기다린 뒤라 옛 번역과 새 구간이
        섞일 수 있다. 그 행이 그대로(fresh이고 세대 번호가 같음)일 때만 새 DB 확정 구간을 더한다.
        """
        with transaction.atomic():
            row = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=cached.pk)
            event = analysis_event(row)
            if _is_fresh(row) and row.generation == started_generation:
                event["grammar"] = _with_parts(rematch_grammar(row, new_closed))
            return event

    def save_rematch(new_closed, span_list=(), answers=(), alternatives=None):
        """다시 매칭해 새로 생긴 구간을 캐시 분석에 더하고 analysis 이벤트를 돌려준다.

        새 용법 → (자격을 얻었으면) 패턴 세트 버전 → 분석 행 순서로 잠근다. 분석 행을 잠근 뒤
        fresh인지, 세대 번호가 같은지, 아직 이 버전으로 다시 매칭하지 않았는지, 새 열쇠가 아직
        저장되지 않았는지 다시 본다. 하나라도 어긋나면 모두 되돌리고 None이다.
        """
        with transaction.atomic():
            patterns.lock_links()
            rows, activated = judged_rows(cached, list(span_list), list(answers), alternatives)
            rows = closed_rows(cached, new_closed) + rows
            if activated:
                patterns.raise_pattern_set_version()
            locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=cached.pk)
            new_keys = {(row.pattern_id, row.start_offset, row.end_offset) for row in rows}
            if (
                not _is_fresh(locked)
                or locked.generation != started_generation
                or locked.matcher_version >= matcher_version
                or new_keys & _stored_keys(locked)
                or _basis_changed(rows, rules)
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
            locked.matcher_version = matcher_version
            locked.save(update_fields=["matcher_version", "updated_at"])
            return analysis_event(locked)

    def rematch(user):
        """패턴 세트 버전이 오른 캐시 분석을 이 요청의 원문으로 다시 매칭한다(#41).

        저장 구간은 지우거나 바꾸지 않고, 저장 열쇠에 없는 새 구간만 더한다. 승인된 용법 완결
        패턴의 구간은 LLM 없이 정한다. 일괄 재처리는 하지 않아 다시 조회한 문장에만 비용이 든다.
        """
        stored_keys = _stored_keys(cached)
        new_closed = [closed for closed in closed_spans if span_key(closed[0]) not in stored_keys]
        new_spans = [span for span in spans if span_key(span) not in stored_keys]
        if new_spans:
            # 판정을 기다리는 동안 새 구간은 '확인 중'으로 보인다.
            usage = RequestUsage.start(UsageLog.Path.LLM, user, cached.pk)
            events = rematch_and_judge(new_closed, new_spans, usage)
            first = next(events)
            return StreamingHttpResponse(_in_thread(chain([first], events)), content_type=_NDJSON)
        # LLM이 필요 없으면 클라이언트를 만들지 않고 한 번에 보낸다.
        event = save_rematch(new_closed)
        RequestUsage.start(UsageLog.Path.DB, user, cached.pk, success=event is not None)
        event = event or rematch_fallback(new_closed)
        events = [
            {"type": "translation", "translation_ko": event["translation_ko"], "ruby": ruby},
            event,
        ]
        return HttpResponse("".join(map(_ndjson, events)), content_type=_NDJSON)

    def rematch_decided(new_closed):
        """재판정에 알릴, 해석이 정해진 구간(이 요청 형태소의 토큰 범위).

        조회 규칙을 거친 저장 결정 구간, 해석 갈림의 주 용법, 새 DB 확정 구간이다. 숫자 표기가
        달라 형태소 경계가 다른 원문이면 저장 위치를 토큰으로 되돌리지 못할 수 있고, 그 구간은
        뺀다.
        """
        starts, ends = {}, {}
        for token in range(len(morphs)):
            start, end = key_span(token, token)
            starts.setdefault(start, token)
            ends[end] = token
        decided = []
        stored = (
            cached.span_matches.filter(
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
                decided.append(
                    {"start_token_id": first, "end_token_id": last, "name": span.usage.name}
                )
        decided += [
            {"start_token_id": span.start_token, "end_token_id": span.end_token, "name": usage.name}
            for span, _, usage, _ in new_closed
        ]
        return decided

    def judge_rematched(new_closed, new_spans, usage):
        """새 판별 대상 구간을 재판정 한 번으로 정하고 저장한다. 저장하지 못했으면 None.

        첫 분석의 판정 규칙(해석 갈림 대안 포함)으로 검증한다. 이 호출이 마지막이라 다시 묻지
        않는다. 번역은 저장된 것으로 "번역과 같은 해석"을 고르게 하고 바꾸지 않는다. LLM 호출과
        검증은 저장 트랜잭션 밖에서 한다.
        """
        client = llm.get_client(usage.record_llm)
        result = client.rematch_judge(
            key_text,
            tokens,
            cached.translation_ko,
            rematch_decided(new_closed),
            _llm_spans(new_spans),
        )
        if not isinstance(result, dict):
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 재판정")
        checked = _validate_recheck_answers(
            result.get("spans"), new_spans, [FIRST_VERDICTS] * len(new_spans), numbers
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
        reject_quotes(validated)
        new_keys = {span_key(span) for span in new_spans}

        def discarded():
            return bool(new_keys & _stored_keys(cached))

        _check_examples(validated, client, key_text, content_tokens, key_span, discarded)
        return save_rematch(new_closed, new_spans, answers, alternatives)

    def rematch_and_judge(new_closed, new_spans, usage):
        """판별 대상 새 구간이 있는 재매칭의 이벤트. 저장 구간과 새 DB 확정 구간, 판별 대상(확인
        중) → 저장 번역 → 재판정·저장 → analysis 순서다.

        재판정이나 저장이 실패하면 아무것도 저장하지 않고 error 대신 대체 응답을 보낸다. 다음
        조회가 다시 시도한다. 로그에는 원문 없이 목적·분석 ID·오류 코드만 남긴다.
        """
        # 먼저 오는 grammar 이벤트는 평평하게 둔다. 하위 박스는 analysis에만 있다(#65).
        yield {
            "type": "grammar",
            "grammar": [item for item, _ in rematch_grammar(cached, new_closed)],
            "checking": checking(new_spans),
        }
        yield translation_event(cached.translation_ko)
        try:
            event = judge_rematched(new_closed, new_spans, usage)
            if event is None:
                raise BusinessError(AnalysisError.FAILED, "재판정 저장 전 분석이 바뀜")
            usage.succeed()
        except BusinessError as e:
            logger.warning(
                "rematch_judge 실패: analysis_id=%s error=%s", cached.pk, e.error_code.code
            )
            event = rematch_fallback(new_closed)
        yield event

    # 학습 단어(조사·조동사·기호·숫자를 뺀 토큰)를 모두 JMdict에서 찾는다. 후보 뜻이 하나면 LLM
    # 없이 정하고, 여럿이면 새 문장 LLM 요청에서 함께 고르게 한다. 못 찾은 토큰은 보이지도
    # 기록하지도 않는다(#96, 사전에 없는 단어는 #97).
    # 캐시 분석은 저장된 단어를 쓰므로 찾지 않는다.
    found = (
        {}
        if cached
        else words.lookup(
            text_to_analyze, morphs, [token for token in range(len(morphs)) if is_vocabulary(token)]
        )
    )
    ambiguous = {token: cands for token, cands in found.items() if len(cands) > 1}
    llm_words = [
        {"token_id": token, "candidates": words.llm_candidates(cands)}
        for token, cands in ambiguous.items()
    ]

    def sentence_words():
        """LLM 응답 전에 보낼 단어(원문 순서). 뜻이 여럿인 단어는 표제·읽기·태그만 보낸다(뜻은
        None). 여러 항목이 걸렸으면(開く あく/ひらく) 고르기 전이라 읽기는 모두 잇고(・) 태그는
        항목들에 공통인 것만 보인다.
        """
        items = []
        for token, cands in found.items():
            start, end = to_original(origins, utf16, morphs[token].begin, morphs[token].end)
            if len(cands) == 1:
                [only] = cands
                items.append(
                    words.response_item(start, end, only.sense.word, only.reading, only.sense)
                )
                continue
            item = words.response_item(start, end, cands[0].sense.word, cands[0].reading, None)
            item["reading"] = "・".join(dict.fromkeys(c.reading for c in cands))
            item["tags"] = sorted(
                set.intersection(*(set(words.word_tags(c.sense.word)) for c in cands))
            )
            items.append(item)
        return items

    def word_spans(chosen):
        """저장할 단어 위치와 뜻(토큰 순서). chosen은 LLM이 고른 {토큰: 뜻 ID}다."""
        stored = []
        for token, cands in found.items():
            sense_id = cands[0].sense.id if len(cands) == 1 else chosen.get(token)
            if sense_id is not None:
                start, end = key_span(token, token)
                stored.append({"start": start, "end": end, "sense_id": sense_id})
        return stored

    def respond(user):
        """요청 쪽: 캐시 분석은 한 번에 보내고, 패턴 세트 버전이 올랐으면 다시 매칭하고, 나머지는
        작업자의 LLM 작업을 기다리며 흘려보낸다.
        """
        if cached and cached.matcher_version >= matcher_version:
            RequestUsage.start(UsageLog.Path.CACHE, user, cached.pk, success=True)
            # 이미 다 있으니 한 번에 보낸다.
            events = [translation_event(cached.translation_ko), analysis_event(cached)]
            return HttpResponse("".join(map(_ndjson, events)), content_type=_NDJSON)
        if cached:
            return rematch(user)
        return StreamingHttpResponse(llm_stream(user, early_events()), content_type=_NDJSON)

    # 이 작업의 LLM 호출(분석·다시 묻기·예문 다시 쓰기)은 한 클라이언트로 해서 요청 전체 마감 시각을
    # 함께 쓴다(run).
    return SimpleNamespace(respond=respond, run=run)
