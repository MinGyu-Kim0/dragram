"""LLM 응답 검증."""

import unicodedata

from analysis import llm, words
from analysis.jmdict import SENSE_TAG_NAMES, WHOLE_WORD_TAGS, to_hiragana
from analysis.models import (
    CONNECTION_FORM_LENGTH,
    KOREAN_EQUIVALENT_LENGTH,
    FunctionTag,
    SpanMatch,
)
from analysis.normalize import (
    has_all_placeholders,
    has_only_known_placeholders,
)
from errors import AnalysisError, BusinessError


def _is_text(value):
    if not isinstance(value, str) or value.strip() == "":
        return False
    try:
        # JSON에는 단독 서로게이트(\ud800 등)가 들어올 수 있지만 UTF-8로는 인코딩할 수 없다.
        value.encode()
    except UnicodeEncodeError:
        return False
    return True


def _is_token_id(value, token_count):
    # bool은 int의 하위 타입이라 따로 거른다.
    return type(value) is int and 0 <= value < token_count


# 구간마다 받을 수 있는 판정. 첫 응답은 모두, 다시 묻기에서 첫 응답의 해석 갈림·미확정
# 구간(RECHECK)은 미발견을 받지 않는다(#40).
FIRST_VERDICTS = frozenset(llm.SPAN_VERDICTS)
RECHECK_VERDICTS = FIRST_VERDICTS - {"unfound"}


def _has_basis(value):
    """대안의 근거가 있는가. 공백·기호·제어 문자를 지우고도 글자가 남아야 한다."""
    return isinstance(value, str) and any(unicodedata.category(ch)[0] not in "ZPSC" for ch in value)


def _validate_alternatives(items, candidates, primary_id, numbers):
    """다시 묻기의 해석 갈림 대안을 검증한다. 틀리면 None, 아니면 [(용법, 대안 번역)](후보 순서).

    근거가 빈 대안은 다른 칸을 보지 않고 그 대안만 버린다. 근거는 그 문장을 풀어 쓴 글이라
    저장하지도 로그에 남기지도 않는다. 대안은 그 구간의 후보 중 주 용법이 아닌 것이고 서로
    달라야 한다. 대안 번역은 주 번역처럼 자리표시자를 빠짐없이 옮겨야 한다.
    """
    if not isinstance(items, list):
        return None
    order = list(candidates)
    chosen = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        if not _has_basis(item.get("basis")):
            continue
        candidate_id, translation = item.get("candidate_id"), item.get("translation_ko")
        if type(candidate_id) is not int or candidate_id not in candidates:
            return None
        if candidate_id == primary_id or candidate_id in chosen:
            return None
        if not _is_text(translation) or not has_all_placeholders(translation, numbers):
            return None
        chosen[candidate_id] = translation
    return [
        (candidates[candidate_id], chosen[candidate_id])
        for candidate_id in sorted(chosen, key=order.index)
    ]


def _validate_span_answers(answers, spans):
    """첫 응답이 후보 구간마다 낸 판정을 검증한다. 하나라도 틀리거나 빠지면 None.

    구간마다 (판정 상태, 고른 용법, 새 용법)을 돌려준다. 용법은 그 구간에 준 후보 안에서만 고를
    수 있다. 미발견이면 그 패턴 아래 더할 새 용법(이름·설명·예문)이 있어야 한다. 해석 갈림은 주
    용법만 받고, 후보가 하나뿐인 구간에서는 갈릴 해석이 없어 틀린 답이다.
    """
    checked = _checked_span_answers(answers, spans, [FIRST_VERDICTS] * len(spans), None)
    return None if checked is None else checked[0]


def _validate_recheck_answers(answers, spans, allowed, numbers):
    """다시 묻기의 판정을 검증한다. 하나라도 틀리거나 빠지면 None, 아니면 (판정들, {구간 순번:
    [(대안 용법, 대안 번역)]}).

    allowed는 구간마다 받을 판정이다. 해석 갈림은 대안까지 검증하고, 근거 있는 대안이 남지 않으면
    미확정이다.
    """
    return _checked_span_answers(answers, spans, allowed, numbers)


def _checked_span_answers(answers, spans, allowed, numbers):
    """두 검증이 함께 쓰는 판정 검증. numbers가 None이면 첫 응답이라 대안을 보지 않는다."""
    if not isinstance(answers, list):
        return None
    judged, alternatives = {}, {}
    for item in answers:
        if not isinstance(item, dict):
            return None
        span_id = item.get("span_id")
        # 구간 ID도 서버가 0부터 매긴 번호라 토큰 ID와 같은 방식으로 본다.
        if not _is_token_id(span_id, len(spans)) or span_id in judged:
            return None
        verdict, candidate_id = item.get("verdict"), item.get("candidate_id")
        if verdict not in allowed[span_id]:
            return None
        if verdict == "divergent":
            candidates = dict(spans[span_id].candidates)
            usage = candidates.get(candidate_id)
            if type(candidate_id) is not int or usage is None:
                return None
            if numbers is None:
                if len(candidates) < 2:
                    return None
                judged[span_id] = (SpanMatch.State.DIVERGENT, usage, None)
                continue
            # 대안 칸이 null이면 대안이 없는 것이다(근거 있는 대안이 없을 때와 같다).
            alts = _validate_alternatives(
                item.get("alternatives") or [], candidates, candidate_id, numbers
            )
            if alts is None:
                return None
            if alts:
                judged[span_id] = (SpanMatch.State.DIVERGENT, usage, None)
                alternatives[span_id] = alts
            else:
                judged[span_id] = (SpanMatch.State.UNRESOLVED, None, None)
        elif verdict == "unresolved":
            judged[span_id] = (SpanMatch.State.UNRESOLVED, None, None)
        elif verdict == "usage":
            # bool은 int의 하위 타입이고 True == 1이라 따로 거른다.
            usage = dict(spans[span_id].candidates).get(candidate_id)
            if type(candidate_id) is not int or usage is None:
                return None
            judged[span_id] = (SpanMatch.State.DECIDED, usage, None)
        elif verdict == "not_applicable":
            judged[span_id] = (SpanMatch.State.NOT_APPLICABLE, None, None)
        elif verdict == "unfound":
            new_usage = item.get("new_usage")
            if not isinstance(new_usage, dict) or not _are_new_texts(new_usage, ("usage_name",)):
                return None
            equivalent = korean_equivalent(new_usage.get("korean_equivalent"))
            new_usage = {
                **new_usage,
                "korean_equivalent": equivalent,
                "function_tags": function_tags(new_usage.get("function_tags")),
            }
            judged[span_id] = (SpanMatch.State.UNFOUND, None, new_usage)
        else:
            return None
    if len(judged) != len(spans):
        return None
    return [judged[span_id] for span_id in range(len(spans))], alternatives


# 새 구문 제안에서 공용 패턴·용법에 들어가는 글
_NEW_PATTERN_TEXTS = ("pattern_name", "usage_name", "explanation_ko")
# grammar_pattern.name·grammar_usage.name 칸 길이. 넘으면 저장할 때 DB 오류가 난다.
_NAME_LENGTH = 255


def _are_new_texts(item, names):
    """새 패턴·용법의 이름(names)·설명·예문을 검증한다."""
    if not all(_is_text(item.get(field)) for field in (*names, "explanation_ko", "example_ja")):
        return False
    # 용법은 모든 문장이 함께 써서 이 문장의 숫자로 되돌릴 수 없으므로 자리표시자를 받지 않는다.
    if not all(
        has_only_known_placeholders(item[field], ()) for field in (*names, "explanation_ko")
    ):
        return False
    return all(len(item[field]) <= _NAME_LENGTH for field in names)


def function_tags(value):
    """LLM이 고른 기능 태그(#151) 중 허용 목록 안의 것(허용 목록 순서, 중복 없음).

    대응 표현처럼 틀려도 용법 등록이나 응답을 실패시키지 않는다. 목록이 아니면 빈 목록이다.
    """
    chosen = {v for v in value if isinstance(v, str)} if isinstance(value, list) else set()
    return [tag for tag in FunctionTag.values if tag in chosen]


def korean_equivalent(value):
    """LLM이 쓴 대응 표현(#152). 글이 아니거나, 자리표시자가 있거나, 상한을 넘으면 None이다.

    용법의 일부일 뿐이라 틀려도 용법 등록이나 응답을 실패시키지 않고 이 칸만 비운다.
    """
    if not _is_text(value):
        return None
    value = value.strip()
    # 용법은 모든 문장이 함께 써서 이 문장의 숫자로 되돌릴 수 없다.
    if not has_only_known_placeholders(value, ()) or len(value) > KOREAN_EQUIVALENT_LENGTH:
        return None
    return value


def _validate_new_patterns(items, token_count):
    """LLM이 제안한 새 구문의 형식을 검증한다. 하나라도 틀리면 None.

    패턴 생성 규칙(빈틈, 처음·끝 아무거나, 재매칭)은 저장할 때 보고, 어긴 제안만 뺀다.
    """
    if not isinstance(items, list):
        return None
    proposals = []
    for item in items:
        if not isinstance(item, dict):
            return None
        tokens = item.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            return None
        for token in tokens:
            if not isinstance(token, dict) or not _is_token_id(token.get("token_id"), token_count):
                return None
            if token.get("fix") not in llm.TOKEN_FIXES:
                return None
        if not _are_new_texts(item, ("pattern_name", "usage_name")):
            return None
        fields = (*_NEW_PATTERN_TEXTS, "example_ja")
        proposals.append(
            {
                "tokens": [(token["token_id"], token["fix"]) for token in tokens],
                **{field: item[field] for field in fields},
                "korean_equivalent": korean_equivalent(item.get("korean_equivalent")),
                "function_tags": function_tags(item.get("function_tags")),
                "connection_form": connection_form(item.get("connection_form")),
            }
        )
    return proposals


def connection_form(value):
    """공용 접속 형태 한 줄. 잘못된 값은 기존 문법·설명에 영향을 주지 않는다(#229)."""
    if not _is_text(value):
        return None
    value = value.strip()
    if (
        len(value) > CONNECTION_FORM_LENGTH
        or not has_only_known_placeholders(value, ())
        or any(unicodedata.category(ch).startswith("C") for ch in value)
    ):
        return None
    return value


def _validate_word_answers(answers, ambiguous):
    """LLM이 고른 단어 뜻을 검증한다. 목록이 아니면 None, 아니면 {토큰: 고른 뜻 ID}.

    후보 밖 ID를 답했거나 답이 없는 토큰은 그 토큰만 뺀다(#96). 단어 하나 때문에 번역·문법까지
    버리면 같은 문장마다 LLM을 다시 불러야 해서다. 같은 토큰에 두 번 답했으면 그 토큰도 뺀다.
    """
    if not isinstance(answers, list):
        return None
    chosen, repeated = {}, set()
    for item in answers:
        if not isinstance(item, dict):
            continue
        token, sense_id = item.get("token_id"), item.get("sense_id")
        # bool은 int의 하위 타입이라 따로 거른다.
        if type(token) is not int or type(sense_id) is not int or token not in ambiguous:
            continue
        if sense_id not in {c.sense.id for c in ambiguous[token]}:
            continue
        if token in chosen:
            repeated.add(token)
        chosen[token] = sense_id
    return {token: sense_id for token, sense_id in chosen.items() if token not in repeated}


# word 표기·읽기 칸 길이
_WORD_TEXT_MAX = 255


def _word_text(value):
    """새 단어의 사전형·읽기로 쓸 값(앞뒤 공백을 뗀다). 빈 값, 너무 긴 값, 숫자·자리표시자가
    든 값(숫자만 다른 문장에 잘못 재사용된다)이면 None이다.
    """
    if not _is_text(value):
        return None
    value = value.strip()
    if len(value) > _WORD_TEXT_MAX or any(ch.isdigit() or ch in "⟨⟩" for ch in value):
        return None
    return value


def _validate_new_words(answers, unknown):
    """1단계 답: 사전에 없는 토큰의 사전형·읽기(#134). {토큰: (사전형, 히라가나 읽기)}.

    unknown은 {토큰: 표층형}이다. 받지 않은 토큰, 형식이 틀린 답, 가나가 아닌 읽기, 두 번 답한
    토큰은 그 토큰만 뺀다. 사전형·읽기는 공용 word에 들어가므로, 토큰보다 훨씬 길면(문장 조각을
    답함) 뺀다. 목록이 아니면 하나도 받지 않은 것으로 본다(단어 때문에 번역·문법을 버리지 않는다).
    """
    found, repeated = {}, set()
    for item in answers if isinstance(answers, list) else []:
        if not isinstance(item, dict):
            continue
        token = item.get("token_id")
        form, reading = _word_text(item.get("dictionary_form")), _word_text(item.get("reading"))
        if type(token) is not int or token not in unknown or form is None or reading is None:
            continue
        # 활용 어미·표기 차이만큼은 늘 수 있다(走っ → 走る, ばか → 馬鹿, 一昨日 → おととい).
        surface = len(unknown[token])
        if not words.is_kana(reading) or len(form) > surface + 3 or len(reading) > 4 * surface + 3:
            continue
        if token in found:
            repeated.add(token)
        found[token] = (form, to_hiragana(reading))
    return {token: value for token, value in found.items() if token not in repeated}


def _validate_name_spans(answers, token_count):
    """이름 구간(#140): [(첫 토큰, 끝 토큰, 종류)]. 토큰이 없거나 범위 밖이거나 이어지지 않거나
    종류가 목록 밖인 항목은 그 항목만 뺀다. 목록이 아니면 판단하지 않은 것(None)으로 본다.
    이름 때문에 번역·문법을 버리지 않고, '이름 없음'([])으로 잘못 저장하지도 않는다.
    """
    if not isinstance(answers, list):
        return None
    found = []
    for item in answers:
        if not isinstance(item, dict) or item.get("type") not in llm.NAME_TYPES:
            continue
        tokens = item.get("token_ids")
        if (
            not isinstance(tokens, list)
            or not tokens
            or not all(_is_token_id(token, token_count) for token in tokens)
            or tokens != list(range(tokens[0], tokens[0] + len(tokens)))
        ):
            continue
        found.append((tokens[0], tokens[-1], item["type"]))
    return found


def _validate_definitions(result, candidates):
    """2단계 답(#134). candidates는 {word_id: 후보 뜻 ID 집합}이다.

    {word_id: (고른 뜻 ID | None, 한국어 뜻, 뜻 태그, 단어 태그)}이고, 답이 없거나 후보 밖 ID를
    골랐거나 새 뜻인데 한국어 뜻이 비었거나 두 번 답한 단어는 뺀다. 태그는 허용 목록 밖 값을 버린다.
    """
    answers = result.get("words") if isinstance(result, dict) else None
    made, repeated = {}, set()
    for item in answers if isinstance(answers, list) else []:
        if not isinstance(item, dict):
            continue
        word_id, sense_id = item.get("word_id"), item.get("sense_id")
        if type(word_id) is not int or word_id not in candidates:
            continue
        meaning = None
        if sense_id is None:
            meaning = item.get("meaning_ko")
            # 문장의 숫자 자리표시자가 공용 뜻에 남지 않게 한다.
            if not _is_text(meaning) or "⟨" in meaning:
                continue
            meaning = meaning.strip()
        elif type(sense_id) is not int or sense_id not in candidates[word_id]:
            continue
        if word_id in made:
            repeated.add(word_id)
        made[word_id] = (
            sense_id,
            meaning,
            _allowed(item.get("sense_tags"), SENSE_TAG_NAMES),
            _allowed(item.get("word_tags"), WHOLE_WORD_TAGS),
        )
    return {word_id: answer for word_id, answer in made.items() if word_id not in repeated}


def _allowed(tags, allowed):
    """허용 목록 안의 태그만(중복 없이, 받은 순서)."""
    return (
        list(dict.fromkeys(t for t in tags if isinstance(t, str) and t in allowed))
        if isinstance(tags, list)
        else []
    )


def _validate_meanings(result, asked):
    """LLM이 만든 한국어 뜻을 검증한다(#97). {뜻 ID: 한국어 뜻}이고, 요청한 뜻(asked)마다 답이
    없거나 빈 답이거나 두 번 답한 뜻은 빠진다(호출하는 쪽이 그 뜻만 실패로 둔다).
    """
    answers = result.get("senses") if isinstance(result, dict) else None
    made, repeated = {}, set()
    for item in answers if isinstance(answers, list) else []:
        if not isinstance(item, dict):
            continue
        sense_id, meaning = item.get("sense_id"), item.get("meaning_ko")
        # bool은 int의 하위 타입이고 True == 1이라 따로 거른다.
        if type(sense_id) is not int or sense_id not in asked or not _is_text(meaning):
            continue
        if sense_id in made:
            repeated.add(sense_id)
        made[sense_id] = meaning.strip()
    return {sense_id: meaning for sense_id, meaning in made.items() if sense_id not in repeated}


def _validate_translation(translation, numbers):
    """번역을 검증한다. 문법·단어보다 먼저 보내므로 따로 검증한다."""
    if not _is_text(translation):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 번역")
    # 자리표시자가 맞지 않는 번역은 숫자가 틀렸을 수 있어 보여주지도 저장하지도 않는다.
    if not has_all_placeholders(translation, numbers):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 번역 자리표시자")


def _validate(result, numbers, token_count, spans, ambiguous, unknown):
    """LLM 응답에서 쓸 값만 꺼낸다. 형식이 틀리거나 자리표시자가 맞지 않으면 ANALYSIS:FAILED."""
    if not isinstance(result, dict):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 객체 아님")
    _validate_translation(result.get("translation_ko"), numbers)
    span_answers = _validate_span_answers(result.get("spans"), spans)
    if span_answers is None:
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 후보 구간")
    new_patterns = _validate_new_patterns(result.get("new_patterns"), token_count)
    if new_patterns is None:
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 새 구문")
    chosen = _validate_word_answers(result.get("words"), ambiguous)
    if chosen is None:
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 단어")
    return {
        "translation_ko": result["translation_ko"],
        "spans": span_answers,
        "new_patterns": new_patterns,
        "words": chosen,
        "new_words": _validate_new_words(result.get("new_words"), unknown),
        "name_spans": _validate_name_spans(result.get("name_spans"), token_count),
    }


def _validate_rewrites(result, count):
    """다시 쓴 예문을 검증한다. 요청한 예문 ID마다 하나씩 있어야 하고, 아니면 None."""
    examples = result.get("examples") if isinstance(result, dict) else None
    if not isinstance(examples, list):
        return None
    rewritten = {}
    for item in examples:
        if not isinstance(item, dict):
            return None
        example_id, text = item.get("example_id"), item.get("example_ja")
        # 예문 ID도 서버가 0부터 매긴 번호라 토큰 ID와 같은 방식으로 본다.
        if not _is_token_id(example_id, count) or example_id in rewritten or not _is_text(text):
            return None
        rewritten[example_id] = text
    if len(rewritten) != count:
        return None
    return [rewritten[example_id] for example_id in range(count)]


def _quotes_whole_sentence(texts, key_text, token_count):
    """LLM이 쓴 글(문법 이름·설명)이 문장 전체(키 텍스트)를 인용했는가.

    기호·공백을 뺀 형태소가 하나뿐인 문장(です, 行く！ 등)이면 그 토큰을 인용하는 것과 같고,
    단어 하나는 사전 표제어 수준의 공용 정보라 허용한다. 형태소가 여럿이면 구간이 문장
    전체여도 원문을 옮긴 것이다. token_count는 기호·공백을 뺀 형태소 수다.
    """
    if token_count <= 1:
        return False
    # 형태소 사이에 공백·가운데점·보이지 않는 문자를 넣어 인용해도(私・は・学生) 원문을
    # 옮긴 것이므로, 양쪽에서 문장부호·기호·공백·형식 문자를 지우고 비교한다.
    compact_key = _letters(key_text)
    if not compact_key:
        # 기호만으로 된 문장은 지우면 비어서 모든 글에 "포함"된다. 인용으로 보지 않는다.
        return False
    return any(compact_key in _letters(text) for text in texts)


def _letters(text):
    """문장부호·기호·공백·형식 문자(유니코드 P·S·Z·C 분류)를 지운다."""
    return "".join(ch for ch in text if unicodedata.category(ch)[0] not in "PSZC")


def reject_quotes(validated, sentence):
    """LLM이 쓴 글이 문장 전체를 인용했으면 ANALYSIS:FAILED다."""
    for item in validated["new_patterns"]:
        form = item.get("connection_form")
        if form and _quotes_whole_sentence([form], sentence.key_text, sentence.content_tokens):
            item["connection_form"] = None
    llm_texts = [item[field] for item in validated["new_patterns"] for field in _NEW_PATTERN_TEXTS]
    llm_texts += [
        new_usage[field]
        for _, _, new_usage in validated["spans"]
        if new_usage is not None
        for field in ("usage_name", "explanation_ko")
    ]
    if _quotes_whole_sentence(llm_texts, sentence.key_text, sentence.content_tokens):
        # 이 글들은 공용 테이블에 들어가므로 원문을 통째로 옮긴 결과는 저장하지 않는다.
        raise BusinessError(AnalysisError.FAILED, "LLM이 쓴 글이 문장 전체를 인용함")
    # 대응 표현은 같은 규칙으로 보되, 인용했으면 그 칸만 비운다(#152).
    for item in [
        *validated["new_patterns"],
        *(new_usage for _, _, new_usage in validated["spans"] if new_usage is not None),
    ]:
        equivalent = item.get("korean_equivalent")
        if equivalent and _quotes_whole_sentence(
            [equivalent], sentence.key_text, sentence.content_tokens
        ):
            item["korean_equivalent"] = None
