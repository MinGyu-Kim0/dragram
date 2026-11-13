import json
import time
from contextlib import closing

import openai
from django.conf import settings
from openai import OpenAI, OpenAIError

from analysis import timing
from analysis.llm_analyze import INSTRUCTIONS, NAME_TYPES, RESPONSE_SCHEMA, TOKEN_FIXES
from analysis.llm_fill import (
    CONNECTION_INSTRUCTIONS,
    CONNECTION_SCHEMA,
    FILL_INSTRUCTIONS,
    FILL_SCHEMA,
)
from analysis.llm_judge import JUDGE_INSTRUCTIONS, judge_schema
from analysis.llm_rewrite import REWRITE_INSTRUCTIONS, REWRITE_SCHEMA
from analysis.llm_rules import (
    ALTERNATIVES_SCHEMA,
    FUNCTION_TAGS_RULE,
    FUNCTION_TAGS_SCHEMA,
    KOREAN_EQUIVALENT_RULE,
    NUMBER_RULES,
    SPAN_VERDICTS,
    span_answers_schema,
)
from analysis.llm_stream import SectionParser
from analysis.llm_words import DEFINE_INSTRUCTIONS, DEFINE_SCHEMA, GLOSS_INSTRUCTIONS, GLOSS_SCHEMA
from analysis.models import UsageLog
from errors import AnalysisError, BusinessError

# 이 모듈은 LLM 호출의 입구다. 호출하는 쪽은 용도별 프롬프트 모듈 대신 이 이름들을 쓴다.
__all__ = [
    "ALTERNATIVES_SCHEMA",
    "CONNECTION_INSTRUCTIONS",
    "CONNECTION_SCHEMA",
    "DEFINE_INSTRUCTIONS",
    "DEFINE_SCHEMA",
    "FILL_INSTRUCTIONS",
    "FILL_SCHEMA",
    "FUNCTION_TAGS_RULE",
    "FUNCTION_TAGS_SCHEMA",
    "GLOSS_INSTRUCTIONS",
    "GLOSS_SCHEMA",
    "INSTRUCTIONS",
    "JUDGE_INSTRUCTIONS",
    "KOREAN_EQUIVALENT_RULE",
    "NAME_TYPES",
    "NUMBER_RULES",
    "OpenAILLMClient",
    "RESPONSE_SCHEMA",
    "REWRITE_INSTRUCTIONS",
    "REWRITE_SCHEMA",
    "SPAN_VERDICTS",
    "SectionParser",
    "TOKEN_FIXES",
    "get_client",
    "judge_schema",
    "span_answers_schema",
]

# 응답 전체를 기다리지 않고 닫히는 대로 넘기는 칸 → 넘길 때의 이름. 번역은 먼저 알리고, 판정은
# 확인 중 카드를, 단어 뜻 고르기는 '뜻을 준비하는 중'을 먼저 풀도록 넘긴다(#204, #205). 그래서
# 스키마에서 이 칸들을 길이가 긴 새 구문보다 앞에 둔다. 모두 응답 전체(result)에도 들어 있다.
_EARLY_SECTIONS = {"translation_ko": "translation", "spans": "spans", "words": "words"}

# 요청 스레드와 사이드 패널을 오래 붙잡지 않게 시간 상한을 둔다(NFR-14). 스트림에서는 연결과
# 조각 사이 대기마다 적용된다.
# 타임아웃 뒤 재시도하면 이미 과금된 요청을 또 보낼 수 있어 재시도하지 않는다.
TIMEOUT_SECONDS = 30

# 조각이 계속 오면 위 상한에 걸리지 않으므로 스트림 전체에도 상한을 둔다.
STREAM_DEADLINE_SECONDS = 60

# 스트림 뒤 보조 호출(다시 묻기·예문 다시 쓰기)까지 요청 하나가 LLM을 기다리는 전체 상한.
# 클라이언트를 만든 때부터 센다. 분석 작업 시간 제한(analysis/jobs.py, 120초)보다 저장할
# 시간만큼 짧아야 하고, 스트림 상한과 조각 대기 상한을 더한 것보다는 길어야 한다.
REQUEST_DEADLINE_SECONDS = 110

MAX_RETRIES = 0


def _transient(error):
    """다시 보내면 나을 수 있는 SDK 오류(연결 오류, 429, 5xx). 타임아웃은 위 이유로 넣지 않는다."""
    return not isinstance(error, openai.APITimeoutError) and isinstance(
        error, (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)
    )


class _NothingReceived(BusinessError):
    """받은 것 없이 일시 오류로 실패한 호출. 요청 마감 안이면 한 번만 다시 보낸다(#99)."""


# 스트림이 실패했거나 끝까지 쓰지 못했음을 알리는 이벤트
_FAILED_EVENTS = {"error", "response.failed", "response.incomplete"}

# 응답(모델명·토큰 사용량)을 싣고 스트림을 끝내는 이벤트. error 이벤트에는 응답이 없다.
_FINAL_EVENTS = {"response.completed", "response.failed", "response.incomplete"}


class OpenAILLMClient:
    """요청 하나가 쓰는 클라이언트. 그 요청의 호출들이 마감 시각 하나를 함께 쓴다.

    보낸 호출마다 record(purpose, model, input_tokens, cached_input_tokens, output_tokens,
    success, attempt, seconds)를 한 번 부른다. 보내지 못했거나 응답이 없으면 토큰은 None이다.
    seconds는 보내기 시작해 끝나기(실패 포함)까지의 시간이다(#216). 마감이 지나 보내지 않은 호출은
    부르지 않는다.
    """

    def __init__(self, record):
        self._record = record
        self._deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES
        )

    def analyze_stream(self, sentence, tokens, spans, decided_spans, words, unknown_words):
        """구조화된 출력을 스트림으로 받는다. 번역을 쓰는 동안 앞부분이 늘 때마다
        ("translation_partial", 검증 전 앞부분)을(#303), 번역이 끝나면 ("translation", 번역)을,
        판정 칸이 끝나면 ("spans", 검증 전 판정)을, 단어 칸이 끝나면 ("words", 검증 전 고른
        뜻)을 먼저 넘기고(#204, #205), 다 받으면 ("result", 검증 전 응답)을 넘긴다. spans는
        등록된 패턴에 걸린 구간과 그 후보 용법이다. decided_spans는 LLM 없이 확정한 구간이라
        답을 받지 않고, 새 구문으로 다시 내지 않게 알리기만 한다. words는 JMdict 후보 뜻이 여럿인
        토큰과 그 후보다(#96). unknown_words는 사전에서 못 찾은 토큰 ID로, 사전형·읽기만
        받는다(#134).

        SDK 오류(타임아웃·인증·연결 끊김 등), 실패·중단 이벤트, 전체 시간 초과, JSON이 아닌
        응답(거절 등)은 ANALYSIS:FAILED다. 아무것도 받기 전에 일시 오류로 실패했으면 요청 마감
        안에서 한 번 더 보낸다(#99).
        """
        args = (sentence, tokens, spans, decided_spans, words, unknown_words)
        try:
            yield from self._stream(1, *args)
        except _NothingReceived:
            if time.monotonic() >= self._deadline:
                raise
            yield from self._stream(2, *args)

    def _stream(self, attempt, sentence, tokens, spans, decided_spans, words, unknown_words):
        """analyze_stream의 호출 한 번. attempt는 시도 차수다."""
        parser = SectionParser()
        # 다시 보낸 스트림도 요청 마감을 넘기지 않는다.
        now = time.monotonic()
        deadline = min(now + STREAM_DEADLINE_SECONDS, self._deadline)
        # 사이드 패널이 연결을 끊어 중간에 닫혀도 보낸 호출은 기록한다.
        final, success, received, sent = None, False, False, timing.clock()
        last_prefix = None
        try:
            stream = self._create(
                min(TIMEOUT_SECONDS, self._deadline - now),
                INSTRUCTIONS + NUMBER_RULES,
                {
                    "sentence": sentence,
                    "tokens": tokens,
                    "spans": spans,
                    "decided_spans": decided_spans,
                    "words": words,
                    "unknown_words": unknown_words,
                },
                "sentence_analysis",
                RESPONSE_SCHEMA,
                stream=True,
            )
            # 사이드 패널이 연결을 끊어 중간에 멈춰도 OpenAI 연결을 닫는다.
            with closing(stream):
                for event in stream:
                    received = True
                    if event.type in _FINAL_EVENTS:
                        final = event.response
                    if time.monotonic() > deadline:
                        raise BusinessError(AnalysisError.FAILED, "LLM 스트림 전체 시간 초과")
                    if event.type in _FAILED_EVENTS:
                        raise BusinessError(AnalysisError.FAILED, f"LLM 스트림 실패: {event.type}")
                    if event.type == "response.output_text.delta":
                        for key, value in parser.feed(event.delta):
                            if key in _EARLY_SECTIONS:
                                yield _EARLY_SECTIONS[key], value
                        # 번역은 닫히기 전에도 앞부분이 늘 때마다 넘긴다(#303).
                        prefix = parser.partial("translation_ko")
                        if prefix and prefix != last_prefix:
                            last_prefix = prefix
                            yield "translation_partial", prefix
            result = parser.result()
            success = True
        except OpenAIError as e:
            failure = _NothingReceived if not received and _transient(e) else BusinessError
            raise failure(AnalysisError.FAILED, "LLM 호출 실패") from e
        finally:
            self._record_call(UsageLog.Purpose.FIRST_RESPONSE, final, success, attempt, sent)
        yield "result", result

    def judge_spans(self, sentence, tokens, translation_ko, decided_spans, recheck_spans, spans):
        """후보 구간만 다시 묻는다. 스트림 없이 받은 검증 전 응답을 돌려준다.

        recheck_spans는 첫 응답에서 해석 갈림·미확정이었던 구간, spans는 같은 형태소 조건의
        기존 패턴으로 다시 묻는 구간이다. recheck_spans가 있을 때만 문장 번역을 함께 받는다.
        decided_spans는 해석이 정해진 구간이라 답을 받지 않는다.
        """
        return self._judge(
            UsageLog.Purpose.REASK,
            "다시 묻기",
            sentence,
            tokens,
            translation_ko,
            decided_spans,
            recheck_spans,
            spans,
        )

    def rematch_judge(self, sentence, tokens, translation_ko, decided_spans, spans):
        """패턴 세트 버전이 올라 다시 매칭한 캐시 문장의 새 판별 대상 구간을 판정한다(#41).

        다시 묻기의 같은 형태소 조건 구간과 지침·스키마를 함께 쓰고 호출 목적만 다르다. 번역은
        저장된 것을 주고 받지 않는다. 검증 전 응답을 돌려준다.
        """
        return self._judge(
            UsageLog.Purpose.REMATCH_JUDGE,
            "재판정",
            sentence,
            tokens,
            translation_ko,
            decided_spans,
            [],
            spans,
        )

    def _judge(
        self, purpose, label, sentence, tokens, translation_ko, decided_spans, recheck_spans, spans
    ):
        """다시 묻기와 재판정이 함께 쓰는 구간 판정. recheck_spans가 있을 때만 번역을 받는다."""
        payload = {
            "sentence": sentence,
            "tokens": tokens,
            "translation_ko": translation_ko,
            "decided_spans": decided_spans,
            "recheck_spans": recheck_spans,
            "spans": spans,
        }
        return self._ask(
            purpose,
            label,
            JUDGE_INSTRUCTIONS + NUMBER_RULES,
            payload,
            "span_judgement",
            judge_schema(bool(recheck_spans)),
        )

    def rewrite_examples(self, sentence, examples):
        """원문을 베껴 거부된 예문들을 한 번에 다시 쓰게 한다. 검증 전 응답을 돌려준다."""
        payload = {"sentence": sentence, "examples": examples}
        return self._ask(
            UsageLog.Purpose.EXAMPLE_REWRITE,
            "예문 다시 쓰기",
            REWRITE_INSTRUCTIONS,
            payload,
            "example_rewrite",
            REWRITE_SCHEMA,
        )

    def gloss_words(self, senses):
        """JMdict 뜻들의 한국어 뜻을 한 번에 만든다(#97). 검증 전 응답을 돌려준다.

        senses는 뜻마다 sense_id·표제·읽기·pos·영어 뜻·뜻 태그다. 문장은 넘기지 않는다.
        """
        return self._ask(
            UsageLog.Purpose.WORD_GLOSS,
            "한국어 뜻",
            GLOSS_INSTRUCTIONS,
            {"senses": senses},
            "word_gloss",
            GLOSS_SCHEMA,
        )

    def define_words(self, sentence, items):
        """사전에 없는 단어의 뜻을 고르거나 만든다(#134 2단계). 검증 전 응답을 돌려준다.

        items는 단어마다 word_id·token_id·사전형·읽기·후보 뜻('뜻 ID: 뜻')이다.
        """
        return self._ask(
            UsageLog.Purpose.WORD_GLOSS,
            "새 단어 뜻",
            DEFINE_INSTRUCTIONS,
            {"sentence": sentence, "words": items},
            "word_definitions",
            DEFINE_SCHEMA,
        )

    def fill_usages(self, usages):
        """이미 있는 용법의 빈 칸(대응 표현 #152, 기능 태그 #151)을 채운다(fill_usages 명령). 검증
        전 응답을 돌려준다.

        usages는 용법마다 usage_id·패턴 이름·형태소 조건·용법 이름·설명·예문이다. 문장 원문은
        넘기지 않는다.
        """
        return self._ask(
            UsageLog.Purpose.USAGE_FILL,
            "용법 채우기",
            FILL_INSTRUCTIONS,
            {"usages": usages},
            "usage_fill",
            FILL_SCHEMA,
        )

    def fill_connection(self, pattern):
        """저장된 공용 패턴·용법만으로 접속 형태를 채운다. 사용자 원문은 받지 않는다."""
        return self._ask(
            UsageLog.Purpose.PATTERN_CONNECTION,
            "접속 형태",
            CONNECTION_INSTRUCTIONS,
            pattern,
            "pattern_connection",
            CONNECTION_SCHEMA,
        )

    def _ask(self, purpose, label, instructions, payload, name, schema):
        """구조화된 출력을 스트림 없이 받는다(_ask_once). 일시 오류로 실패했으면 한 번 더
        보낸다(#99). 마감이 지났으면 _ask_once가 보내지 않는다.
        """
        args = (purpose, label, instructions, payload, name, schema)
        try:
            return self._ask_once(1, *args)
        except _NothingReceived:
            return self._ask_once(2, *args)

    def _ask_once(self, attempt, purpose, label, instructions, payload, name, schema):
        """구조화된 출력을 스트림 없이 한 번 받는다. attempt는 시도 차수, purpose는 사용 기록의
        호출 목적, label은 로그용 이름이다.

        요청 마감 시각까지 남은 시간만 기다리고, 이미 지났으면 보내지 않는다. SDK 오류, 끝까지
        쓰지 못한 응답, JSON이 아닌 응답(거절 등)은 ANALYSIS:FAILED다.
        """
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise BusinessError(AnalysisError.FAILED, f"LLM {label} 전에 요청 시간 초과")
        response, success, sent = None, False, timing.clock()
        try:
            response = self._create(
                min(TIMEOUT_SECONDS, remaining), instructions, payload, name, schema
            )
            if response.status != "completed":
                raise BusinessError(AnalysisError.FAILED, f"LLM {label} 실패: {response.status}")
            try:
                answer = json.loads(response.output_text)
            except json.JSONDecodeError as e:
                raise BusinessError(AnalysisError.FAILED, f"LLM {label} 응답이 JSON이 아님") from e
            success = True
            return answer
        except OpenAIError as e:
            failure = _NothingReceived if _transient(e) else BusinessError
            raise failure(AnalysisError.FAILED, f"LLM {label} 호출 실패") from e
        finally:
            self._record_call(purpose, response, success, attempt, sent)

    def _create(self, timeout, instructions, payload, name, schema, **extra):
        """구조화된 출력 요청을 보낸다. 스트림 호출과 일반 호출이 같은 인자로 묻는다. extra는
        stream처럼 호출마다 더하는 인자다.
        """
        return self._client.responses.create(
            timeout=timeout,
            model=settings.OPENAI_MODEL,
            reasoning={"effort": settings.OPENAI_REASONING_EFFORT},
            # 이어 쓰기를 하지 않으므로 OpenAI에 응답 상태를 남기지 않는다.
            store=False,
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
            text={
                "format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}
            },
            **extra,
        )

    def _record_call(self, purpose, response, success, attempt, sent):
        """보낸 호출 하나를 기록한다. response는 SDK 응답이고 받지 못했으면 None이다. sent는 보내기
        시작한 시각(timing.clock)이다.
        """
        model, tokens = settings.OPENAI_MODEL, (None, None, None)
        if response is not None:
            model = response.model
            if (usage := response.usage) is not None:
                tokens = (
                    usage.input_tokens,
                    usage.input_tokens_details.cached_tokens,
                    usage.output_tokens,
                )
        input_tokens, cached_input_tokens, output_tokens = tokens
        self._record(
            purpose=purpose,
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            success=success,
            attempt=attempt,
            seconds=timing.seconds_since(sent),
        )


def get_client(record):
    return OpenAILLMClient(record)
