import json
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from analysis import llm, timing
from analysis.llm import OpenAILLMClient, SectionParser
from errors import AnalysisError, BusinessError


@pytest.fixture
def recorded():
    """클라이언트가 남긴 LLM 호출 기록"""
    return []


def recorder(recorded):
    return lambda **call: recorded.append(call)


@pytest.fixture
def llm_client(settings, recorded, monkeypatch):
    # 실제 OpenAI는 부르지 않는다. SDK 호출(responses.create)만 바꿔 끼운다.
    settings.OPENAI_API_KEY = "test-key"
    # 호출 시간을 재는 시계는 멈춰 둔다. 시간을 보는 테스트만 돌린다.
    monkeypatch.setattr(timing, "clock", lambda: 0.0)
    return OpenAILLMClient(recorder(recorded))


def stream_with(llm_client, monkeypatch, create):
    monkeypatch.setattr(llm_client._client.responses, "create", create)


def deltas(*texts):
    """SDK 스트림 이벤트 대신 쓰는 출력 텍스트 조각 이벤트들"""
    return [SimpleNamespace(type="response.output_text.delta", delta=text) for text in texts]


def stream_of(events):
    """SDK 스트림처럼 close가 있는 이벤트 스트림"""
    yield from events


def usage(input_tokens, cached_tokens, output_tokens):
    """SDK 응답의 토큰 사용량"""
    return SimpleNamespace(
        input_tokens=input_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        output_tokens=output_tokens,
    )


def response_with(status="completed", output_text='{"spans": []}'):
    return SimpleNamespace(
        status=status, output_text=output_text, model="gpt-test-2026", usage=usage(50, 0, 10)
    )


def test_stream_gives_translation_first_and_then_the_whole_result(llm_client, monkeypatch):
    stream_with(
        llm_client,
        monkeypatch,
        lambda **kwargs: (
            stream_of(deltas('{"translation_ko": "번역"', ', "spans": []', ', "words": []}'))
            if kwargs.get("stream")
            else None
        ),
    )

    # 판정·단어 칸은 닫히는 대로 응답 전체보다 먼저 나온다(#204, #205).
    assert list(llm_client.analyze_stream("文", [], [], [], [], [])) == [
        ("translation", "번역"),
        ("spans", []),
        ("words", []),
        ("result", {"translation_ko": "번역", "spans": [], "words": []}),
    ]


def test_stream_gives_the_growing_translation_prefix_before_it_closes(llm_client, monkeypatch):
    chunks = ['{"translation_ko": "', "나는", "", ' 학생"', ', "spans": []}']
    stream_with(llm_client, monkeypatch, lambda **kwargs: stream_of(deltas(*chunks)))

    # 앞부분은 늘어났을 때만 넘긴다(빈 앞부분, 그대로인 조각은 넘기지 않는다).
    assert list(llm_client.analyze_stream("文", [], [], [], [], []))[:3] == [
        ("translation_partial", "나는"),
        ("translation", "나는 학생"),
        ("spans", []),
    ]


def test_response_writes_translation_then_judgments_then_word_choices():
    # 구조화 출력은 스키마 속성 순서대로 쓴다. 먼저 넘기는 칸이 길이가 긴 새 구문보다 앞이다(#205).
    order = ["translation_ko", "spans", "words", "new_patterns", "new_words", "name_spans"]
    assert list(llm.RESPONSE_SCHEMA["properties"]) == order
    assert llm.RESPONSE_SCHEMA["required"] == order


def test_openai_error_becomes_analysis_failure(llm_client, monkeypatch):
    # 타임아웃·인증·속도 제한 등 SDK 예외는 모두 OpenAIError를 상속한다.
    def fail(**_):
        raise openai.OpenAIError("timeout")

    stream_with(llm_client, monkeypatch, fail)

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], [], [], [], []))
    assert raised.value.error_code == AnalysisError.FAILED


def test_openai_error_in_the_middle_of_the_stream_becomes_analysis_failure(llm_client, monkeypatch):
    def events():
        yield from deltas('{"translation_ko": "번역"')
        raise openai.OpenAIError("connection reset")

    stream_with(llm_client, monkeypatch, lambda **_: events())

    stream = llm_client.analyze_stream("文", [], [], [], [], [])
    assert next(stream) == ("translation", "번역")
    with pytest.raises(BusinessError) as raised:
        next(stream)
    assert raised.value.error_code == AnalysisError.FAILED


def failed_event(event_type):
    """실패·중단 이벤트. error 이벤트에는 응답이 없다."""
    if event_type == "error":
        return SimpleNamespace(type=event_type)
    status = event_type.removeprefix("response.")
    return SimpleNamespace(
        type=event_type, response=SimpleNamespace(status=status, model="gpt-test", usage=None)
    )


@pytest.mark.parametrize("event_type", ["error", "response.failed", "response.incomplete"])
def test_failed_stream_event_becomes_analysis_failure(llm_client, monkeypatch, event_type):
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of([*deltas('{"translation_ko": "번역"'), failed_event(event_type)]),
    )

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], [], [], [], []))
    assert raised.value.error_code == AnalysisError.FAILED


@pytest.mark.parametrize("output_text", ["", "not json"])
def test_output_that_is_not_json_becomes_analysis_failure(llm_client, monkeypatch, output_text):
    stream_with(llm_client, monkeypatch, lambda **_: stream_of(deltas(output_text)))

    with pytest.raises(BusinessError) as raised:
        list(llm_client.analyze_stream("文", [], [], [], [], []))
    assert raised.value.error_code == AnalysisError.FAILED


def feed_all(parser, chunks):
    """조각을 차례로 넣고, 닫힌 맨 위 칸마다 (조각 번호, 칸 이름, 값)을 돌려준다."""
    return [(i, key, value) for i, chunk in enumerate(chunks) for key, value in parser.feed(chunk)]


def test_translation_comes_out_as_soon_as_its_string_closes():
    parser = SectionParser()
    chunks = ['{"transla', 'tion_ko": "나는 ', '학생입니다."', ', "grammar": [', "]}"]

    assert feed_all(parser, chunks) == [
        (2, "translation_ko", "나는 학생입니다."),
        (4, "grammar", []),
    ]
    assert parser.result() == {"translation_ko": "나는 학생입니다.", "grammar": []}


def test_escaped_quote_does_not_end_the_translation_early():
    parser = SectionParser()
    # 조각이 이스케이프 가운데(\ 와 ")에서 끊긴다.
    chunks = ['{"translation_ko": "그는 \\', '"간다\\"', ' \\u3042"', ', "words": []}']

    assert feed_all(parser, chunks)[0] == (2, "translation_ko", '그는 "간다" あ')


def test_section_comes_out_when_it_closes_before_later_sections_arrive():
    # 판정 칸(#204)은 뒤 칸이 오기 전에 나온다. 글 안의 괄호·따옴표는 칸을 닫지 않는다.
    parser = SectionParser()
    chunks = [
        '{"translation_ko": "번역", "spans": [{"span_id": 0, "new_usage": ',
        '{"usage_name": "괄호 ] } \\" 안"}}',
        "]",
        ', "new_patterns": [], "count": 3',
        "}",
    ]

    assert feed_all(parser, chunks) == [
        (0, "translation_ko", "번역"),
        (2, "spans", [{"span_id": 0, "new_usage": {"usage_name": '괄호 ] } " 안'}}]),
        (3, "new_patterns", []),
        (4, "count", 3),
    ]


def test_scalar_and_object_sections_with_newlines_come_out():
    parser = SectionParser()
    chunks = ['{\n  "ok": true,\n  "none": null', ',\n  "n": -1.5,\n  "obj": {"a": [1]}\n', "}"]

    assert feed_all(parser, chunks) == [
        (0, "ok", True),
        (1, "none", None),
        (1, "n", -1.5),
        (1, "obj", {"a": [1]}),
    ]


def partials(parser, chunks, key="translation_ko"):
    """조각을 차례로 넣으며, 조각마다 아직 닫히지 않은 그 칸 문자열의 앞부분을 모은다."""
    found = []
    for chunk in chunks:
        parser.feed(chunk)
        found.append(parser.partial(key))
    return found


def test_unclosed_translation_comes_out_as_its_prefix_grows():
    # 번역은 칸이 닫히기 전에도 글자 단위로 보인다(#303). 닫히면 앞부분은 없다.
    chunks = ['{"transla', 'tion_ko": "', "나는 ", "학생", '입니다."', ', "spans": []}']

    assert partials(SectionParser(), chunks) == [None, "", "나는 ", "나는 학생", None, None]


def test_prefix_does_not_end_in_a_cut_escape():
    # 조각이 이스케이프·\u 가운데, 서로게이트 쌍 사이에서 끊겨도 깨진 글자를 내지 않는다.
    chunks = ['{"translation_ko": "그는 \\', '"간다\\', '" \\u30', "42 \\ud83d", "\\ude00"]

    assert partials(SectionParser(), chunks) == [
        "그는 ",
        '그는 "간다',
        '그는 "간다" ',
        '그는 "간다" あ ',
        '그는 "간다" あ 😀',
    ]


def test_prefix_is_only_for_the_asked_section():
    parser = SectionParser()
    parser.feed('{"translation_ko": "번역", "spans": [{"basis": "근거')

    assert parser.partial("translation_ko") is None
    assert parser.partial("basis") is None


def test_result_that_is_not_json_becomes_analysis_failure():
    parser = SectionParser()
    parser.feed('{"translation_ko": "번역", "gram')

    with pytest.raises(BusinessError) as raised:
        parser.result()
    assert raised.value.error_code == AnalysisError.FAILED


def test_section_with_invalid_escape_becomes_analysis_failure():
    parser = SectionParser()

    with pytest.raises(BusinessError) as raised:
        parser.feed('{"translation_ko": "잘못된 \\x 이스케이프"')
    assert raised.value.error_code == AnalysisError.FAILED


def test_stream_longer_than_the_total_deadline_becomes_analysis_failure(llm_client, monkeypatch):
    # 조각이 계속 와서 조각 사이 타임아웃에는 걸리지 않아도 전체 시간 상한에서 멈춘다.
    now = iter(range(0, 1000, 25))
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of(deltas('{"translation_ko": "번역"', *[" "] * 10, "}")),
    )

    stream = llm_client.analyze_stream("文", [], [], [], [], [])
    assert next(stream) == ("translation", "번역")
    with pytest.raises(BusinessError) as raised:
        next(stream)
    assert raised.value.error_code == AnalysisError.FAILED


def test_request_carries_sentence_tokens_and_candidate_spans(llm_client, monkeypatch):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return stream_of(deltas('{"translation_ko": "번역"}'))

    stream_with(llm_client, monkeypatch, create)
    tokens = [{"id": 0, "surface": "は"}]
    spans = [
        {
            "span_id": 0,
            "start_token_id": 0,
            "end_token_id": 0,
            "candidates": [{"candidate_id": 1, "name": "주제", "explanation_ko": "설명"}],
        }
    ]

    decided = [{"start_token_id": 0, "end_token_id": 0, "name": "주제"}]
    words = [{"token_id": 0, "candidates": ["7: topic marker"]}]

    list(llm_client.analyze_stream("は", tokens, spans, decided, words, [3]))

    [request] = requests
    assert json.loads(request["input"]) == {
        "sentence": "は",
        "tokens": tokens,
        "spans": spans,
        "decided_spans": decided,
        "words": words,
        "unknown_words": [3],
    }


def judge_with(llm_client, monkeypatch, response):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response

    stream_with(llm_client, monkeypatch, create)
    return requests


SPANS = [
    {
        "span_id": 0,
        "start_token_id": 0,
        "end_token_id": 0,
        "candidates": [{"candidate_id": 1, "name": "주제", "explanation_ko": "설명"}],
    }
]


def test_judge_spans_sends_sentence_translation_and_spans_and_returns_the_answer(
    llm_client, monkeypatch
):
    answer = '{"spans": [{"span_id": 0, "verdict": "usage", "candidate_id": 1, "new_usage": null}]}'
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )
    tokens = [{"id": 0, "surface": "は"}]

    result = llm_client.judge_spans("は", tokens, "는", [], [], SPANS)

    assert result == json.loads(answer)
    [request] = requests
    assert json.loads(request["input"]) == {
        "sentence": "は",
        "tokens": tokens,
        "translation_ko": "는",
        "decided_spans": [],
        "recheck_spans": [],
        "spans": SPANS,
    }
    assert request["text"]["format"]["strict"] is True
    # 같은 조건 구간만 다시 물으면 번역을 받지 않는다.
    assert request["text"]["format"]["schema"]["required"] == ["spans"]
    assert request["timeout"] == llm.TIMEOUT_SECONDS


def test_judge_spans_asks_for_the_translation_only_when_rechecking(llm_client, monkeypatch):
    answer = '{"translation_ko": "는", "spans": []}'
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )
    decided = [{"start_token_id": 0, "end_token_id": 0, "name": "주제"}]

    llm_client.judge_spans("は", [], "는", decided, SPANS, [])

    [request] = requests
    assert json.loads(request["input"])["decided_spans"] == decided
    assert json.loads(request["input"])["recheck_spans"] == SPANS
    assert request["text"]["format"]["schema"]["required"] == ["translation_ko", "spans"]


def test_rematch_judge_sends_the_stored_translation_and_new_spans_without_asking_translation(
    llm_client, monkeypatch
):
    answer = '{"spans": [{"span_id": 0, "verdict": "usage", "candidate_id": 1, "new_usage": null}]}'
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )
    decided = [{"start_token_id": 1, "end_token_id": 1, "name": "주격"}]

    result = llm_client.rematch_judge("は", [], "는", decided, SPANS)

    assert result == json.loads(answer)
    [request] = requests
    assert json.loads(request["input"]) == {
        "sentence": "は",
        "tokens": [],
        "translation_ko": "는",
        "decided_spans": decided,
        "recheck_spans": [],
        "spans": SPANS,
    }
    # 다시 묻기와 같은 지침·스키마를 쓰고, 번역은 받지 않는다.
    assert request["instructions"] == llm.JUDGE_INSTRUCTIONS + llm.NUMBER_RULES
    assert request["text"]["format"]["schema"]["required"] == ["spans"]


@pytest.mark.parametrize(
    "response",
    [
        openai.OpenAIError("timeout"),
        response_with(status="incomplete", output_text='{"spans": []}'),
        response_with(status="completed", output_text="not json"),
    ],
)
def test_judge_spans_failure_becomes_analysis_failure(llm_client, monkeypatch, response):
    judge_with(llm_client, monkeypatch, response)

    with pytest.raises(BusinessError) as raised:
        llm_client.judge_spans("は", [], "는", [], [], SPANS)
    assert raised.value.error_code == AnalysisError.FAILED


def test_follow_up_call_waits_only_until_the_request_deadline(settings, monkeypatch):
    # 요청 하나의 호출들이 함께 쓰는 마감 시각까지 남은 시간만 기다린다.
    settings.OPENAI_API_KEY = "test-key"
    now = iter([0, llm.REQUEST_DEADLINE_SECONDS - 10])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    llm_client = OpenAILLMClient(recorder([]))
    answer = '{"spans": []}'
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )

    llm_client.judge_spans("は", [], "는", [], [], SPANS)

    [request] = requests
    assert request["timeout"] == 10


def test_follow_up_call_after_the_request_deadline_is_not_sent(settings, monkeypatch):
    settings.OPENAI_API_KEY = "test-key"
    now = iter([0, llm.REQUEST_DEADLINE_SECONDS])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    llm_client = OpenAILLMClient(recorder([]))
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text="{}")
    )

    with pytest.raises(BusinessError) as raised:
        llm_client.rewrite_examples("文", EXAMPLES)
    assert raised.value.error_code == AnalysisError.FAILED
    assert requests == []


EXAMPLES = [
    {
        "example_id": 0,
        "pattern_name": "ている",
        "usage_name": "진행",
        "explanation_ko": "동작이 이어지고 있다",
        "rejected_example": "昨日図書館で本を見ている",
    }
]


def test_rewrite_examples_sends_sentence_and_rejected_examples_and_returns_the_answer(
    llm_client, monkeypatch
):
    answer = '{"examples": [{"example_id": 0, "example_ja": "雨が降っている"}]}'
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )

    result = llm_client.rewrite_examples("昨日図書館で本を読んでいる", EXAMPLES)

    assert result == json.loads(answer)
    [request] = requests
    assert json.loads(request["input"]) == {
        "sentence": "昨日図書館で本を読んでいる",
        "examples": EXAMPLES,
    }
    assert request["text"]["format"]["strict"] is True


@pytest.mark.parametrize(
    "response",
    [
        openai.OpenAIError("timeout"),
        response_with(status="incomplete", output_text='{"examples": []}'),
        response_with(status="completed", output_text="not json"),
    ],
)
def test_rewrite_examples_failure_becomes_analysis_failure(llm_client, monkeypatch, response):
    judge_with(llm_client, monkeypatch, response)

    with pytest.raises(BusinessError) as raised:
        llm_client.rewrite_examples("文", EXAMPLES)
    assert raised.value.error_code == AnalysisError.FAILED


SENSES = [
    {
        "sense_id": 7,
        "dictionary_form": "食べる",
        "reading": "たべる",
        "pos": "v1,vt",
        "gloss_en": ["to eat"],
        "tags": ["transitive"],
    }
]


def test_gloss_words_sends_only_the_senses_and_returns_the_answer(llm_client, monkeypatch):
    answer = '{"senses": [{"sense_id": 7, "meaning_ko": "먹다"}]}'
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )

    result = llm_client.gloss_words(SENSES)

    assert result == json.loads(answer)
    [request] = requests
    # 문장은 넘기지 않는다(근거는 사전 칸뿐이다).
    assert json.loads(request["input"]) == {"senses": SENSES}
    assert request["text"]["format"]["strict"] is True


def test_define_words_sends_the_sentence_and_words_and_returns_the_answer(llm_client, monkeypatch):
    answer = (
        '{"words": [{"word_id": 0, "sense_id": null, "meaning_ko": "달리다",'
        ' "sense_tags": [], "word_tags": ["verb"]}]}'
    )
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )
    items = [
        {
            "word_id": 0,
            "token_id": 0,
            "dictionary_form": "走る",
            "reading": "はしる",
            "candidates": [],
        }
    ]

    result = llm_client.define_words("走っている", items)

    assert result == json.loads(answer)
    [request] = requests
    assert json.loads(request["input"]) == {"sentence": "走っている", "words": items}
    assert request["text"]["format"]["strict"] is True


def test_fill_usages_sends_only_the_usages_and_returns_the_answer(
    llm_client, monkeypatch, recorded
):
    answer = '{"usages": [{"usage_id": 3, "korean_equivalent": "~고 있다"}]}'
    requests = judge_with(
        llm_client, monkeypatch, response_with(status="completed", output_text=answer)
    )
    usages = [
        {
            "usage_id": 3,
            "pattern_name": "ている",
            "usage_name": "진행",
            "explanation_ko": "동작이 이어지고 있다",
            "example_ja": "雨が降っている",
        }
    ]

    result = llm_client.fill_usages(usages)

    assert result == json.loads(answer)
    [request] = requests
    assert json.loads(request["input"]) == {"usages": usages}
    assert request["text"]["format"]["strict"] is True
    assert [call["purpose"] for call in recorded] == ["usage_fill"]


def test_every_new_usage_answer_asks_for_its_korean_equivalent():
    new_pattern = llm.RESPONSE_SCHEMA["properties"]["new_patterns"]["items"]
    [new_usage, _] = llm.span_answers_schema(True)["items"]["properties"]["new_usage"]["anyOf"]
    for schema in (new_pattern, new_usage):
        assert "korean_equivalent" in schema["required"]
    assert "korean_equivalent" in llm.INSTRUCTIONS
    assert "korean_equivalent" in llm.JUDGE_INSTRUCTIONS
    assert llm.KOREAN_EQUIVALENT_RULE in llm.JUDGE_INSTRUCTIONS


def test_connection_uses_shared_pattern_knowledge_and_records_its_purpose(
    llm_client, monkeypatch, recorded
):
    answer = '{"connection_form": "동사 て형 + いる"}'
    requests = judge_with(llm_client, monkeypatch, response_with(output_text=answer))
    pattern = {"pattern_name": "ている", "morphemes": [], "usages": []}

    assert llm_client.fill_connection(pattern) == json.loads(answer)

    [request] = requests
    assert json.loads(request["input"]) == pattern
    assert request["text"]["format"]["strict"] is True
    assert [call["purpose"] for call in recorded] == ["pattern_connection"]
    new_pattern = llm.RESPONSE_SCHEMA["properties"]["new_patterns"]["items"]
    assert "connection_form" in new_pattern["required"]


def completed_event(model="gpt-test-2026", status="completed", type_="response.completed"):
    return SimpleNamespace(
        type=type_, response=SimpleNamespace(status=status, model=model, usage=usage(100, 40, 20))
    )


def test_stream_records_first_response_with_its_model_and_tokens(llm_client, monkeypatch, recorded):
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of([*deltas('{"translation_ko": "번역"}'), completed_event()]),
    )

    list(llm_client.analyze_stream("文", [], [], [], [], []))

    assert recorded == [
        {
            "purpose": "first_response",
            "model": "gpt-test-2026",
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "output_tokens": 20,
            "success": True,
            "attempt": 1,
            "seconds": 0.0,
        }
    ]


@pytest.mark.parametrize(
    "call",
    [
        lambda c: list(c.analyze_stream("文", [], [], [], [], [])),
        lambda c: c.judge_spans("は", [], "는", [], [], SPANS),
    ],
)
def test_call_records_how_long_it_took_from_sending_to_the_end(
    llm_client, monkeypatch, recorded, call
):
    # 보내기 시작할 때 10초, 기록할 때 13.5초다(#216).
    now = iter([10.0, 13.5])
    monkeypatch.setattr(timing, "clock", lambda: next(now))
    events = [*deltas('{"translation_ko": "번역"}'), completed_event()]
    monkeypatch.setattr(
        llm_client._client.responses,
        "create",
        lambda stream=False, **_: stream_of(events) if stream else response_with(),
    )

    call(llm_client)

    assert [c["seconds"] for c in recorded] == [3.5]


def test_failed_stream_records_failure_with_the_tokens_it_used(llm_client, monkeypatch, recorded):
    # 끝까지 쓰지 못한 응답도 과금되므로 토큰을 남긴다.
    event = completed_event(status="incomplete", type_="response.incomplete")
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of([*deltas('{"translation_ko": "번역"'), event]),
    )

    with pytest.raises(BusinessError):
        list(llm_client.analyze_stream("文", [], [], [], [], []))

    [call] = recorded
    assert call["success"] is False
    assert (call["input_tokens"], call["output_tokens"]) == (100, 20)


def test_stream_that_could_not_be_sent_records_failure_without_tokens(
    llm_client, monkeypatch, recorded, settings
):
    def fail(**_):
        raise openai.OpenAIError("timeout")

    stream_with(llm_client, monkeypatch, fail)

    with pytest.raises(BusinessError):
        list(llm_client.analyze_stream("文", [], [], [], [], []))

    assert recorded == [
        {
            "purpose": "first_response",
            "model": settings.OPENAI_MODEL,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "success": False,
            "attempt": 1,
            "seconds": 0.0,
        }
    ]


def test_stream_that_is_not_json_records_failure(llm_client, monkeypatch, recorded):
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of([*deltas("I cannot help"), completed_event()]),
    )

    with pytest.raises(BusinessError):
        list(llm_client.analyze_stream("文", [], [], [], [], []))

    [call] = recorded
    assert call["success"] is False
    assert call["input_tokens"] == 100


def test_stream_closed_by_the_reader_still_records_the_call(llm_client, monkeypatch, recorded):
    # 사이드 패널이 연결을 끊어 번역 뒤에 멈춰도 이미 보낸 호출은 남긴다.
    stream_with(
        llm_client,
        monkeypatch,
        lambda **_: stream_of(deltas('{"translation_ko": "번역"', ', "words": []}')),
    )

    stream = llm_client.analyze_stream("文", [], [], [], [], [])
    next(stream)
    stream.close()

    [call] = recorded
    assert call["purpose"] == "first_response"
    assert call["success"] is False


@pytest.mark.parametrize(
    "call, purpose",
    [
        (lambda c: c.judge_spans("は", [], "는", [], [], SPANS), "reask"),
        (lambda c: c.rematch_judge("は", [], "는", [], SPANS), "rematch_judge"),
        (lambda c: c.rewrite_examples("文", EXAMPLES), "example_rewrite"),
        (lambda c: c.gloss_words(SENSES), "word_gloss"),
    ],
)
def test_follow_up_call_records_its_purpose_model_and_tokens(
    llm_client, monkeypatch, recorded, call, purpose
):
    judge_with(llm_client, monkeypatch, response_with())

    call(llm_client)

    assert recorded == [
        {
            "purpose": purpose,
            "model": "gpt-test-2026",
            "input_tokens": 50,
            "cached_input_tokens": 0,
            "output_tokens": 10,
            "success": True,
            "attempt": 1,
            "seconds": 0.0,
        }
    ]


@pytest.mark.parametrize(
    "response",
    [response_with(status="incomplete"), response_with(output_text="not json")],
)
def test_failed_follow_up_call_records_failure_with_its_tokens(
    llm_client, monkeypatch, recorded, response
):
    judge_with(llm_client, monkeypatch, response)

    with pytest.raises(BusinessError):
        llm_client.judge_spans("は", [], "는", [], [], SPANS)

    [call] = recorded
    assert call["success"] is False
    assert call["input_tokens"] == 50


def test_follow_up_call_that_raised_records_failure_without_tokens(
    llm_client, monkeypatch, recorded
):
    def fail(**_):
        raise openai.OpenAIError("timeout")

    monkeypatch.setattr(llm_client._client.responses, "create", fail)

    with pytest.raises(BusinessError):
        llm_client.rewrite_examples("文", EXAMPLES)

    [call] = recorded
    assert (call["purpose"], call["success"], call["input_tokens"]) == (
        "example_rewrite",
        False,
        None,
    )


def test_follow_up_call_not_sent_after_the_deadline_is_not_recorded(settings, monkeypatch):
    settings.OPENAI_API_KEY = "test-key"
    now = iter([0, llm.REQUEST_DEADLINE_SECONDS])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    recorded = []
    llm_client = OpenAILLMClient(recorder(recorded))

    with pytest.raises(BusinessError):
        llm_client.rewrite_examples("文", EXAMPLES)

    assert recorded == []


# LLM 일시 오류의 1회 재시도(#99). 받은 것 없이 일시 오류로 실패한 호출만 마감 안에서 한 번 더
# 보낸다.
REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


def rate_limited():
    return openai.RateLimitError(
        "rate limited", response=httpx.Response(429, request=REQUEST), body=None
    )


def server_error():
    return openai.InternalServerError(
        "server error", response=httpx.Response(503, request=REQUEST), body=None
    )


def failing_first(error, then):
    """처음 한 번은 error를 내고, 그다음부터는 then()을 돌려주는 SDK 호출"""
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise error
        return then()

    return create, calls


@pytest.mark.parametrize(
    "error", [rate_limited(), server_error(), openai.APIConnectionError(request=REQUEST)]
)
def test_transient_error_is_sent_once_more_and_recorded_as_attempt_2(
    llm_client, monkeypatch, recorded, error
):
    create, calls = failing_first(error, lambda: response_with(output_text='{"examples": []}'))
    monkeypatch.setattr(llm_client._client.responses, "create", create)

    assert llm_client.rewrite_examples("文", EXAMPLES) == {"examples": []}

    assert len(calls) == 2
    assert [(c["attempt"], c["success"]) for c in recorded] == [(1, False), (2, True)]


def test_second_transient_failure_becomes_analysis_failure(llm_client, monkeypatch, recorded):
    def fail(**_):
        raise rate_limited()

    monkeypatch.setattr(llm_client._client.responses, "create", fail)

    with pytest.raises(BusinessError):
        llm_client.rewrite_examples("文", EXAMPLES)

    assert [c["attempt"] for c in recorded] == [1, 2]


@pytest.mark.parametrize(
    "error",
    [
        openai.APITimeoutError(request=REQUEST),
        openai.AuthenticationError(
            "no key", response=httpx.Response(401, request=REQUEST), body=None
        ),
    ],
)
def test_timeout_and_other_errors_are_not_sent_again(llm_client, monkeypatch, recorded, error):
    create, calls = failing_first(error, lambda: response_with(output_text="{}"))
    monkeypatch.setattr(llm_client._client.responses, "create", create)

    with pytest.raises(BusinessError):
        llm_client.rewrite_examples("文", EXAMPLES)

    assert len(calls) == 1


def test_answer_that_fails_validation_is_not_sent_again(llm_client, monkeypatch):
    calls = []

    def bad(**kwargs):
        calls.append(kwargs)
        return response_with(output_text="JSON 아님")

    monkeypatch.setattr(llm_client._client.responses, "create", bad)

    with pytest.raises(BusinessError):
        llm_client.rewrite_examples("文", EXAMPLES)

    assert len(calls) == 1


def test_transient_error_is_not_sent_again_after_the_request_deadline(settings, monkeypatch):
    settings.OPENAI_API_KEY = "test-key"
    # 클라이언트를 만들 때 0, 첫 호출 때 0, 다시 보내려 할 때는 마감이 지났다.
    now = iter([0, 0, llm.REQUEST_DEADLINE_SECONDS])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(now))
    recorded = []
    llm_client = OpenAILLMClient(recorder(recorded))
    create, calls = failing_first(rate_limited(), lambda: response_with(output_text="{}"))
    monkeypatch.setattr(llm_client._client.responses, "create", create)

    with pytest.raises(BusinessError):
        llm_client.rewrite_examples("文", EXAMPLES)

    assert len(calls) == 1


def test_stream_that_failed_before_anything_arrived_is_sent_once_more(
    llm_client, monkeypatch, recorded
):
    create, calls = failing_first(
        openai.APIConnectionError(request=REQUEST),
        lambda: stream_of(deltas('{"translation_ko": "번역"}')),
    )
    stream_with(llm_client, monkeypatch, create)

    assert list(llm_client.analyze_stream("文", [], [], [], [], [])) == [
        ("translation", "번역"),
        ("result", {"translation_ko": "번역"}),
    ]
    assert [(c["attempt"], c["success"]) for c in recorded] == [(1, False), (2, True)]


def test_stream_that_failed_after_something_arrived_is_not_sent_again(llm_client, monkeypatch):
    calls = []

    def broken_stream():
        yield from deltas('{"translation_ko": "번')
        raise openai.APIConnectionError(request=REQUEST)

    def create(**kwargs):
        calls.append(kwargs)
        return broken_stream()

    stream_with(llm_client, monkeypatch, create)

    with pytest.raises(BusinessError):
        list(llm_client.analyze_stream("文", [], [], [], [], []))

    assert len(calls) == 1


# 스트리밍 분석과 일반 구조화 응답, 두 SDK 호출 경로
CALL_PATHS = [
    (
        lambda c: list(c.analyze_stream("文", [], [], [], [], [])),
        lambda: stream_of(deltas('{"translation_ko": "번역"}')),
        [("translation", "번역"), ("result", {"translation_ko": "번역"})],
    ),
    (
        lambda c: c.gloss_words(SENSES),
        lambda: response_with(output_text='{"glosses": []}'),
        {"glosses": []},
    ),
]


@pytest.mark.parametrize("effort", ["low", "medium"])
@pytest.mark.parametrize("call, create_result, expected", CALL_PATHS)
def test_calls_send_the_configured_reasoning_effort(
    llm_client, monkeypatch, settings, recorded, effort, call, create_result, expected
):
    settings.OPENAI_REASONING_EFFORT = effort
    sent = []

    def create(**kwargs):
        sent.append(kwargs["reasoning"])
        return create_result()

    stream_with(llm_client, monkeypatch, create)

    assert call(llm_client) == expected
    assert sent == [{"effort": effort}]
    assert recorded[-1]["success"] is True


@pytest.mark.parametrize("call, create_result, expected", CALL_PATHS)
def test_calls_ask_openai_not_to_store_the_response(
    llm_client, monkeypatch, call, create_result, expected
):
    sent = []

    def create(**kwargs):
        sent.append(kwargs.get("store"))
        return create_result()

    stream_with(llm_client, monkeypatch, create)

    assert call(llm_client) == expected
    assert sent == [False]
