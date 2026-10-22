import hashlib
import json
import re
import unicodedata
from itertools import chain

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from analysis import llm, patterns
from analysis.models import GrammarUsage, ReviewStatus, SentenceAnalysis, SpanMatch
from analysis.morphology import morphemes
from analysis.normalize import (
    NORMALIZE_VERSION,
    analysis_text,
    has_all_placeholders,
    has_only_known_placeholders,
    key_pieces,
    number_ends,
    restore_numbers,
)
from analysis.positions import key_offsets, to_analysis, to_key, to_original, utf16_offsets
from analysis.ruby import ruby_pieces
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error


def _numbers_before_particle(text, morphs):
    """원문에서 바로 뒤에 조사(助詞)가 오는 숫자의 자리표시자 번호."""
    particle_starts = {m.begin for m in morphs if m.pos == "助詞"}
    return {n for n, end in enumerate(number_ends(text), start=1) if end in particle_starts}


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
            }
        )
    return proposals


_WORD_TEXTS = ("lemma", "reading", "meaning_ko")

# 읽기는 가나(장음 ー, 반복 부호 포함)로만 쓰고 가나가 한 글자는 있어야 한다. 가타카나 블록의
# 문장부호(・ ゠)는 가나가 아니다. 숫자와 겹치는 토큰은 단어에서 빠지므로 자리표시자도 받지
# 않는다. 외래어(사전에 없는 새 말 포함)는 가타카나 그대로 두므로 히라가나로 바꾸지 않는다.
_KANA = "\u3041-\u3096\u309d\u309e\u30a1-\u30fa\u30fd\u30fe\u31f0-\u31ff"
_READING = re.compile(rf"[{_KANA}\u30fc]*[{_KANA}][{_KANA}\u30fc]*")


def _validate_words(words, numbers, token_count, is_vocabulary):
    """LLM이 고른 단어 항목을 검증한다. 하나라도 틀리면 None.

    학습할 단어가 아닌 토큰(is_vocabulary가 거짓)을 고른 항목은 나머지를 보지 않고 뺀다.
    지침을 어긴 단어 하나 때문에 번역·문법까지 버리면 같은 문장마다 LLM을 다시 불러야 해서다.
    """
    if not isinstance(words, list):
        return None
    items = []
    seen = set()
    for item in words:
        if not isinstance(item, dict) or not _is_token_id(item.get("token_id"), token_count):
            return None
        # 같은 토큰을 다시 고른 항목은 뺀다(토큰마다 이 문장에서의 뜻은 하나다).
        if not is_vocabulary(item["token_id"]) or item["token_id"] in seen:
            continue
        seen.add(item["token_id"])
        texts = [item.get(field) for field in _WORD_TEXTS]
        if not all(_is_text(text) for text in texts):
            return None
        if not _READING.fullmatch(item["reading"]):
            return None
        # 사전형·뜻도 응답할 때 숫자를 되돌리므로 없는 번호의 자리표시자는 받지 않는다.
        if not all(has_only_known_placeholders(text, numbers) for text in texts):
            return None
        items.append({"token": item["token_id"], **{field: item[field] for field in _WORD_TEXTS}})
    return items


def _validate_translation(translation, numbers):
    """번역을 검증한다. 문법·단어보다 먼저 보내므로 따로 검증한다."""
    if not _is_text(translation):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 번역")
    # 자리표시자가 맞지 않는 번역은 숫자가 틀렸을 수 있어 보여주지도 저장하지도 않는다.
    if not has_all_placeholders(translation, numbers):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 번역 자리표시자")


def _validate(result, numbers, token_count, is_vocabulary, spans):
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
    words = _validate_words(result.get("words"), numbers, token_count, is_vocabulary)
    if words is None:
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 단어")
    return {
        "translation_ko": result["translation_ko"],
        "spans": span_answers,
        "new_patterns": new_patterns,
        "words": words,
    }


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


def _copy_units(key, fixed_spans, aligned):
    """복사 검사에 쓰는 키 텍스트의 (단위, 길이에 세는가)들. 기호·공백은 지운다.

    fixed_spans는 패턴에서 고정한 토큰의 (패턴 안 순서, 키 텍스트 start, end) 목록이고, 그
    글자는 길이에 세지 않는다. aligned면 고정 토큰 하나를 그 순서를 표시로 한 단위로 묶어,
    표기가 달라도(くる·来る, 활용형) 같은 자리의 고정 토큰끼리 같게 한다. 아니면 글자 그대로
    둔다.
    """
    marks = {}
    for seq, start, end in fixed_spans:
        for i in range(start, end):
            marks.setdefault(i, (seq, start))
    units = []
    for i, ch in enumerate(key):
        if i in marks and aligned:
            if marks[i] != marks.get(i - 1):
                units.append((marks[i][:1], False))
        elif _letters(ch):
            units.append((ch, i not in marks))
    return units


def _copies_part(example, original):
    """예문이 원문의 연속된 일부를 기준 길이 이상 그대로 썼는가. 둘 다 _copy_units의 단위다.

    예문에는 그 문법이 들어갈 수밖에 없으므로 원문의 고정 토큰은 길이에 세지 않는다. 다만
    고정 토큰을 사이에 두고 앞뒤를 이어서 베낀 것은 한 번의 복사로 센다. 구간 안의 아무거나
    토큰은 원문 글자라 센다.
    """
    length = settings.EXAMPLE_COPY_LENGTH
    example = [unit for unit, _ in example]
    # counted[j]: 원문 앞 단위와 예문 j번째 단위에서 끝나는 공통 연속 구간의 센 글자 수
    # (공통이 아니면 None)
    counted = [None] * len(example)
    for unit, counts in original:
        previous = [None, *counted[:-1]]
        counted = [
            (previous[j] or 0) + counts if example[j] == unit else None for j in range(len(example))
        ]
        if any(c is not None and c >= length for c in counted):
            return True
    return False


# 새 예문 검사 결과. 원문을 베껴 거부된 예문만 다시 쓰게 한다.
_EXAMPLE_OK, _EXAMPLE_COPIED, _EXAMPLE_UNUSABLE = "ok", "copied", "unusable"


def _example_verdict(example, conditions, key_text, content_tokens, fixed_spans):
    """새 예문을 검사한다. 패턴에 걸리지 않는 등 원문과 상관없이 쓸 수 없으면 unusable, 그렇지
    않은데 원문을 베꼈으면 copied(다시 쓰게 함), 쓸 수 있으면 ok다.
    """
    if len(example) > patterns.EXAMPLE_MAX_LENGTH or not has_only_known_placeholders(example, ()):
        return _EXAMPLE_UNUSABLE
    text, _ = analysis_text(example)
    if not text:
        return _EXAMPLE_UNUSABLE
    pieces, _ = key_pieces(text)
    example_key = "".join(pieces)
    # 원문 키 텍스트와 같거나 전체를 포함하면 베낀 것이다(문장 인용과 같은 비교). 형태소가
    # 하나뿐인 원문은 포함만 허용하고, 원문 그대로인 예문은 형태소 수와 상관없이 거부한다.
    # 다시 써도 원문을 베끼지 않는 것만 고쳐지므로, 쓸 수 없는 예문은 베낀 것보다 먼저 가린다.
    morphs = morphemes(text)
    starts = patterns.match_starts(conditions, morphs)
    if not starts:
        return _EXAMPLE_UNUSABLE
    if _letters(example_key) == _letters(key_text):
        return _EXAMPLE_COPIED
    if _quotes_whole_sentence([example_key], key_text, content_tokens):
        return _EXAMPLE_COPIED
    offsets = key_offsets(pieces)
    example_fixed = [
        (seq, *to_key(offsets, morphs[start + seq].begin, morphs[start + seq].end))
        for start in starts
        for seq, c in enumerate(conditions)
        if c != patterns.ANY
    ]
    # 예문의 패턴 매치와 맞춰 보고, 매치 밖에서 원문 고정 토큰을 같은 글자로 베낀 것도 본다.
    for aligned in (True, False):
        if _copies_part(
            _copy_units(example_key, example_fixed if aligned else [], aligned),
            _copy_units(key_text, fixed_spans, aligned),
        ):
            return _EXAMPLE_COPIED
    return _EXAMPLE_OK


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


# 학습할 단어가 아닌 토큰의 품사(문장부호, 공백, 문법 쪽에서 다루는 조사·조동사)
_NON_WORD_POS = {"補助記号", "空白", "助詞", "助動詞"}


def _stored_words(words, morphs, offsets):
    """토큰 ID로 고른 단어 항목을 키 텍스트 구간으로 바꿔 저장할 모양으로 만든다."""
    stored = []
    for item in words:
        morph = morphs[item["token"]]
        begin, end = morph.begin, morph.end
        key_start, key_end = to_key(offsets, begin, end)
        stored.append(
            {"start": key_start, "end": key_end, **{field: item[field] for field in _WORD_TEXTS}}
        )
    return stored


def _quotes_whole_sentence(texts, key_text, token_count):
    """LLM이 쓴 글(문법 이름·설명, 단어 사전형·읽기·뜻)이 문장 전체(키 텍스트)를 인용했는가.

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


# 화면에 보이는 구간 판정
_SHOWN_STATES = (
    SpanMatch.State.DECIDED,
    SpanMatch.State.DIVERGENT,
    SpanMatch.State.UNRESOLVED,
)


def _grammar_response(analysis, offsets, origins, utf16, restore):
    """용법이 정해진 구간, 해석 갈림, 미확정 구간을 이 요청 원문의 UTF-16 위치로 보인다.

    같은 분석을 표기가 다른 원문(앞 공백, 괄호, 숫자 자릿수 등)이 함께 쓰므로, 요청마다
    그 원문 기준으로 다시 계산한다. 검수 상태는 저장하지 않고 볼 때마다 정한다(ADR 0003):
    고른 용법, 그 용법이 속한 패턴, 실제로 매칭된 패턴 중 하나라도 반려됐으면 빼고, 미검수면
    'AI 생성·미검수'다. 해석 갈림의 대안도 하나씩 같게 보고, 반려된 대안만 뺀다(주 용법 쪽이
    반려면 구간째 뺀다). 미확정은 매칭된 패턴만 본다.
    """
    spans = list(
        analysis.span_matches.filter(state__in=_SHOWN_STATES)
        .select_related("pattern", "usage__pattern")
        .order_by("start_offset", "end_offset", "id")
    )
    alternative_usages = GrammarUsage.objects.select_related("pattern").in_bulk(
        [alt["usage_id"] for span in spans for alt in span.alternatives or []]
    )
    grammar = []
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
                            "translation_ko": restore(alt["translation_ko"]),
                            "review_status": review_status,
                        }
                    )
        grammar.append(item)
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
        "review_status": review_status,
    }


def _unresolved_item(span, offsets, origins, utf16):
    """미확정 구간의 응답 항목. 이름은 매칭된 패턴의 것이고 설명은 없다. 패턴이 반려됐으면 None."""
    if span.pattern.status == ReviewStatus.REJECTED:
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
        "review_status": ("pending" if span.pattern.status == ReviewStatus.PENDING else "approved"),
    }


def _review_status(pattern, usage):
    """화면에 보일 검수 상태(ADR 0003). 고른 용법, 그 용법이 속한 패턴, 실제로 매칭된 패턴 중
    하나라도 반려됐으면 None(보이지 않음), 미검수면 pending이다.
    """
    statuses = {usage.status, usage.pattern.status, pattern.status}
    if ReviewStatus.REJECTED in statuses:
        return None
    return "pending" if ReviewStatus.PENDING in statuses else "approved"


def _closed_usage(span):
    """용법 완결로 LLM 없이 확정할 구간이면 (후보 ID, 그 용법), 아니면 None(구간 판정 절차
    2단계). 승인된 용법 완결 패턴이고, 반려되지 않은 용법이 승인된 하나뿐이어야 한다. 용법 완결
    표시가 보장하지만 분석 때도 다시 본다.
    """
    pattern = span.pattern
    if not pattern.usage_closed or pattern.status != ReviewStatus.APPROVED:
        return None
    if len(span.candidates) != 1:
        return None
    candidate = span.candidates[0]
    return candidate if candidate[1].status == ReviewStatus.APPROVED else None


def _words_response(stored, offsets, origins, utf16, restore):
    """저장된 단어 항목의 키 텍스트 구간을 이 요청 원문의 UTF-16 위치로 바꾼다.

    사전형·뜻의 자리표시자도 번역처럼 이 원문의 숫자로 되돌린다(restore).
    """
    words = []
    for item in stored:
        start, end = to_original(origins, utf16, *to_analysis(offsets, item["start"], item["end"]))
        words.append(
            {
                "start": start,
                "end": end,
                **{field: restore(item[field]) for field in _WORD_TEXTS},
                # JMdict 없이 LLM이 만든 뜻이라 검수 전이다(#10).
                "review_status": "pending",
            }
        )
    return words


def _llm_spans(spans):
    """LLM에 줄 후보 구간. 구간 ID는 이 목록의 순번이다."""
    return [
        {
            "span_id": span_id,
            "start_token_id": span.start_token,
            "end_token_id": span.end_token,
            "candidates": [
                {"candidate_id": candidate_id, "name": u.name, "explanation_ko": u.explanation_ko}
                for candidate_id, u in span.candidates
            ],
        }
        for span_id, span in enumerate(spans)
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


def _is_fresh(analysis):
    """다시 분석하지 않고 쓸 수 있는 분석인가."""
    return analysis.draft_analysis is not None and not analysis.is_stale


class _SavedByAnother(Exception):  # noqa: N818
    """다시 채우려던 분석 행을 그사이 다른 요청이 먼저 채웠다."""


class _PatternTaken(Exception):  # noqa: N818
    """새 패턴을 등록하는 사이 다른 요청이 같은 조건의 패턴을 먼저 등록했다."""


def _ruby_response(pieces, origins, utf16):
    """분석 텍스트 기준 루비 조각을 이 요청 원문의 UTF-16 위치로 바꾼다."""
    ruby = []
    for start, end, reading in pieces:
        start, end = to_original(origins, utf16, start, end)
        ruby.append({"start": start, "end": end, "reading": reading})
    return ruby


# 응답은 줄 단위 JSON(한 줄에 이벤트 하나)이다(#27).
# translation(번역, 루비) → analysis(번역, 문법, 단어) 순서다. 번역 전의 실패는 다른 API
# 오류처럼 상태 코드로, 번역을 보낸 뒤의 실패는 error 이벤트로 알린다.
_NDJSON = "application/x-ndjson"


def _ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


def _errors_as_event(events):
    """응답을 시작한 뒤의 BusinessError는 상태 코드를 바꿀 수 없어 error 이벤트로 알린다.
    이미 보낸 번역은 사이드 패널에 그대로 남는다.
    """
    try:
        yield from events
    except BusinessError as e:
        log_business_error(e)
        yield {"type": "error", "error": e.error_code.code}


# 테스트 단계라 로그인 없이 연다. 로그인 없는 사용을 정식으로 허용한다는 결정은 아니다(#10).
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def analyze(request):
    sentence = request.data.get("text") if isinstance(request.data, dict) else None
    if not _is_text(sentence):
        raise BusinessError(AnalysisError.TEXT_REQUIRED, "분석할 문장이 없음")

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
                saved.draft_analysis["words"], offsets, origins, utf16, restore
            ),
        }

    # 임시 분석을 받기 전에 저장된 행(draft_analysis가 NULL)과 stale 행은 다시 분석한다.
    existing = SentenceAnalysis.objects.filter(sentence_hash=sentence_hash).first()
    cached = existing if existing is not None and _is_fresh(existing) else None
    # 다시 분석하는 동안 영향 범위의 패턴·용법 상태가 바뀌면 이 값이 올라 저장하지 않는다.
    started_generation = existing.generation if existing is not None else 0
    if cached:
        # 이미 다 있으니 한 번에 보낸다.
        events = [translation_event(cached.translation_ko), analysis_event(cached)]
        return HttpResponse("".join(map(_ndjson, events)), content_type=_NDJSON)
    # stale 행의 옛 결과는 다시 분석하는 동안 '재분석 중'으로 보이도록 LLM보다 먼저 보낸다(#60).
    # 저장된 임시 분석을 그대로 내보내지 않고 analysis 이벤트와 같은 경로로 만들어, 반려된 구간은
    # 빠지고 검수 상태는 지금 지식 상태로 다시 계산된다.
    previous = None
    if existing is not None and existing.draft_analysis is not None:
        previous = {**analysis_event(existing), "type": "previous", "ruby": ruby}

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
    # 승인된 용법 완결 패턴의 구간은 LLM 없이 확정하고, 나머지만 후보로 묻는다. 확정 구간은 LLM이
    # 새 구문으로 다시 내지 않도록 알리기만 한다(#39). 분석에는 매칭 직전에 읽은 패턴 세트 버전을
    # 기록한다. 그 뒤에 활성화된 패턴은 다음 조회가 다시 매칭해 찾는다(#41).
    matcher_version = patterns.pattern_set_version()
    matched = patterns.candidate_spans(morphs)
    # (구간, 후보 ID, 용법)
    closed_spans, spans = [], []
    for span in matched:
        closed = _closed_usage(span)
        if closed is None:
            spans.append(span)
        else:
            closed_spans.append((span, *closed))
    llm_spans = _llm_spans(spans)
    decided_spans = [
        {"start_token_id": span.start_token, "end_token_id": span.end_token, "name": usage.name}
        for span, _, usage in closed_spans
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

    def saved_by_another():
        """첫 호출을 기다리는 사이 다른 요청이 이 문장의 분석을 저장했는가."""
        return SentenceAnalysis.objects.filter(
            sentence_hash=sentence_hash, draft_analysis__isnull=False, is_stale=False
        ).exists()

    def check_examples(validated):
        """새 패턴·새 용법의 예문을 저장 전에 검사해, 쓸 수 있는 예문을 "checked_example"에
        둔다(없으면 None). validated 안의 제안·새 용법을 제자리에서 고친다.

        원문을 베껴 거부된 예문은 한 번에 묶어 한 번만 다시 쓰게 하고, 다시 쓴 예문도 같은
        검사를 통과해야 쓴다. 같은 용법에 이미 통과한 예문이 있으면 다시 쓰지 않는다(그 예문을
        쓴다). 다시 쓰기가 실패하면 예문 없이 둔다. 보조 호출 하나 때문에 분석 전체를 버리지
        않는다. 이미 검사한 예문은 다시 보지 않는다(다시 묻기 뒤 재시도). LLM 호출이라 저장
        트랜잭션 밖에서 부른다.
        """

        def fixed_spans(start_token, conditions):
            """패턴에서 고정한 토큰의 (패턴 안 순서, 키 텍스트 start, end)들"""
            return [
                (i, *key_span(start_token + i, start_token + i))
                for i, c in enumerate(conditions)
                if c != patterns.ANY
            ]

        # (예문을 담은 제안·새 용법, 같은 용법인지 가르는 열쇠, 패턴 이름, 형태소 조건,
        #  고정 토큰 구간)
        targets = [
            (
                p,
                (patterns.morpheme_key(p["conditions"]), p["usage_name"]),
                p["pattern_name"],
                p["conditions"],
                fixed_spans(p["tokens"][0][0], p["conditions"]),
            )
            for p in validated["new_patterns"]
            if "checked_example" not in p and p["existing"] is None and p["conditions"] is not None
        ]
        targets += [
            (
                n,
                (span.pattern.id, n["usage_name"]),
                span.pattern.name,
                span.conditions,
                fixed_spans(span.start_token, span.conditions),
            )
            for span, (_, _, n) in zip(validated["span_list"], validated["spans"], strict=True)
            if n is not None and "checked_example" not in n
        ]
        # 기존 패턴에 이미 있는 이름의 새 용법은 더하지 않으므로(patterns.add_usage) 검사하지
        # 않는다. 다시 쓰기를 보내도 버려진다.
        taken = set(
            GrammarUsage.objects.filter(
                pattern__in=[span.pattern for span in validated["span_list"]]
            ).values_list("pattern_id", "name")
        )
        copied, usable = [], set()
        for holder, usage_key, pattern_name, conditions, fixed in targets:
            if usage_key in taken:
                holder["checked_example"] = None
                continue
            verdict = _example_verdict(
                holder["example_ja"], conditions, key_text, content_tokens, fixed
            )
            holder["checked_example"] = holder["example_ja"] if verdict == _EXAMPLE_OK else None
            if verdict == _EXAMPLE_OK:
                usable.add(usage_key)
            elif verdict == _EXAMPLE_COPIED:
                copied.append((holder, usage_key, pattern_name, conditions, fixed))
        copied = [item for item in copied if item[1] not in usable]
        if not copied or saved_by_another():
            return
        try:
            result = client.rewrite_examples(
                key_text,
                [
                    {
                        "example_id": example_id,
                        "pattern_name": pattern_name,
                        "usage_name": holder["usage_name"],
                        "explanation_ko": holder["explanation_ko"],
                        "rejected_example": holder["example_ja"],
                    }
                    for example_id, (holder, _, pattern_name, _, _) in enumerate(copied)
                ],
            )
            rewritten = _validate_rewrites(result, len(copied))
            if rewritten is None:
                raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 예문 다시 쓰기")
        except BusinessError as e:
            log_business_error(e)
            return
        for (holder, _, _, conditions, fixed), text in zip(copied, rewritten, strict=True):
            verdict = _example_verdict(text, conditions, key_text, content_tokens, fixed)
            if verdict == _EXAMPLE_OK:
                holder["checked_example"] = text

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
            elif pattern.status == ReviewStatus.REJECTED:
                rest.append({**proposal, "existing": pattern})
            else:
                span = patterns.span_of(pattern, proposal["tokens"][0][0], next_id)
                next_id += len(span.candidates)
                asked.append(span)
        if not asked and not recheck:
            return {**validated, "new_patterns": rest}
        if saved_by_another():
            # 그 결과를 쓰므로(save_once) 버려질 재질문을 보내지 않는다.
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

    def span_matches(saved, validated, final):
        """판정한 후보 구간과 새 구문을 구간 매칭으로 만든다. 새 구문은 이때 등록한다.

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
        rows = []
        for span, candidate_id, usage in closed_spans:
            start, end = key_span(span.start_token, span.end_token)
            rows.append(
                SpanMatch(
                    analysis=saved,
                    pattern=span.pattern,
                    usage=usage,
                    start_offset=start,
                    end_offset=end,
                    state=SpanMatch.State.DECIDED,
                    decided_by=SpanMatch.DecidedBy.SINGLE_USAGE,
                    candidates=[{"candidate_id": candidate_id, "usage_id": usage.id}],
                )
            )
        judged = list(zip(validated["span_list"], validated["spans"], strict=True))
        # 기존 용법으로 설명되지 않는 구간은 같은 패턴 아래 새 용법을 더한다. 동시 요청이 같은
        # 이름의 용법을 서로 다른 순서로 더하면 유일성 대기가 엇갈려 교착이 나므로 (패턴, 이름)
        # 순서로 더한다. 이 응답에서 이미 더한 (패턴, 이름)이면 그 용법을 함께 쓴다.
        additions = sorted(
            (span.pattern.morpheme_key, new_usage["usage_name"], index)
            for index, (span, (_, _, new_usage)) in enumerate(judged)
            if new_usage is not None
        )
        # 용법 예문은 같은 (패턴, 이름)의 답 중 검사를 통과한 첫 예문이다(check_examples).
        usage_examples = {}
        for _, name, index in additions:
            span, (_, _, new_usage) = judged[index]
            if usage_examples.get((span.pattern.id, name)) is None:
                usage_examples[span.pattern.id, name] = new_usage["checked_example"]
        added, new_usages = {}, {}
        # 용법 0개 패턴에 첫 용법을 붙이거나 새 패턴을 활성화하면 패턴 세트 버전을 올린다.
        activated = False
        for _, name, index in additions:
            span, (_, _, new_usage) = judged[index]
            if (span.pattern.id, name) not in added:
                added[span.pattern.id, name], matchable = patterns.add_usage(
                    span.pattern,
                    name,
                    new_usage["explanation_ko"],
                    usage_examples[span.pattern.id, name],
                )
                activated |= matchable
            new_usages[index] = added[span.pattern.id, name]
        for index, (span, (state, usage, new_usage)) in enumerate(judged):
            start, end = key_span(span.start_token, span.end_token)
            if new_usage is not None:
                usage = new_usages[index]
                if usage is not None:
                    state = SpanMatch.State.DECIDED
            alternatives = None
            if state == SpanMatch.State.DIVERGENT:
                alternatives = [
                    {"usage_id": alt.id, "translation_ko": translation}
                    for alt, translation in validated["alternatives"][index]
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
                    alternatives=alternatives,
                )
            )

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
        SpanMatch.objects.bulk_create(rows)

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
        llm_texts += [item[field] for item in validated["words"] for field in _WORD_TEXTS]
        if _quotes_whole_sentence(llm_texts, key_text, content_tokens):
            # 이 글들은 공용 테이블에 들어가므로 원문을 통째로 옮긴 결과는 저장하지 않는다.
            raise BusinessError(AnalysisError.FAILED, "LLM이 쓴 글이 문장 전체를 인용함")

    def save(validated, final=False):
        """검증한 결과를 공용 캐시에 저장하고 분석 이벤트를 돌려준다.

        저장하는 사이 다른 요청이 같은 조건의 패턴을 먼저 등록했으면, 저장을 되돌리고 그 패턴의
        용법 목록으로 다시 물은 뒤 한 번만 다시 저장한다.
        """
        # 다시 물어 받은 새 용법도 공용 테이블에 들어가므로 다시 본다.
        reject_quotes(validated)
        check_examples(validated)
        draft = {"words": _stored_words(validated["words"], morphs, offsets)}

        # 분석 행과 구간·새 패턴을 함께 저장하고 응답을 만든다. 다른 요청이 먼저 저장한 문장이면
        # 그 결과를 쓰고, 이번 결과의 구간·패턴은 저장하지 않는다.
        try:
            with transaction.atomic():
                saved, outdated = save_once(validated, draft, final)
                event = analysis_event(saved)
                if outdated:
                    # 분석하는 사이 영향 범위가 바뀌었다. 이번 결과는 보내되 저장하지 않고,
                    # stale로 남겨 다음 요청이 다시 분석하게 한다.
                    transaction.set_rollback(True)
                return event
        except _PatternTaken:
            # LLM 호출은 트랜잭션 밖에서 한다.
            return save(ask_again(validated), final=True)

    def save_once(validated, draft, final):
        """분석 행을 만들거나 다시 채우고 구간 매칭을 저장한다. (행, 시작 뒤 세대 번호가
        바뀌었는가)를 돌려준다. 호출하는 쪽이 트랜잭션을 연다.
        """
        saved, created = SentenceAnalysis.objects.get_or_create(
            sentence_hash=sentence_hash,
            defaults={
                "normalize_version": NORMALIZE_VERSION,
                "normalized_length": len(key_text),
                "status": SentenceAnalysis.Status.COMPLETE,
                "translation_ko": validated["translation_ko"],
                "draft_analysis": draft,
                "matcher_version": matcher_version,
            },
        )
        if created:
            span_matches(saved, validated, final)
            return saved, False
        if _is_fresh(saved):
            return saved, False
        # 임시 분석을 받기 전에 저장된 행이나 stale 행이면 이번 결과로 통째로 바꾼다. 상태
        # 전이(analysis.review)가 패턴 → 패턴 세트 버전 → 분석 순서로 잠그므로, 분석 행은 패턴
        # 쪽을 다 쓴 뒤 마지막에 잠근다.
        try:
            with transaction.atomic():
                saved.span_matches.all().delete()
                span_matches(saved, validated, final)
                locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=saved.pk)
                if _is_fresh(locked):
                    raise _SavedByAnother
        except _SavedByAnother, IntegrityError:
            # 그사이 다른 요청이 먼저 채웠다. 이번에 쓴 구간·패턴은 되돌리고 그 값을 쓴다. 같은
            # 구간을 먼저 넣은 요청이 있으면 구간 유일성 제약에 걸린다(#41).
            return SentenceAnalysis.objects.get(pk=saved.pk), False
        locked.translation_ko = validated["translation_ko"]
        locked.draft_analysis = draft
        locked.is_stale = False
        # 세대 번호가 같으면 그사이 더 높은 버전으로 저장된 적이 없지만, 값은 낮추지 않는다.
        locked.matcher_version = max(locked.matcher_version, matcher_version)
        locked.save(
            update_fields=[
                "translation_ko",
                "draft_analysis",
                "is_stale",
                "matcher_version",
                "updated_at",
            ]
        )
        return locked, locked.generation != started_generation

    def closed_grammar():
        """용법 완결로 확정한 구간의 응답 항목(원문 순서)."""
        grammar = []
        for span, _, usage in sorted(
            closed_spans, key=lambda c: (c[0].start_token, c[0].end_token)
        ):
            start, end = key_span(span.start_token, span.end_token)
            grammar.append(_grammar_item(span.pattern, usage, start, end, offsets, origins, utf16))
        return grammar

    def checking():
        """판별 대상 구간의 원문 위치와 후보 용법의 이름·검수 상태(원문 순서). 후보 이름도 LLM이
        만든 지식이라 미검수면 미검수로 보인다(불변식). 반려된 용법은 후보에 없다.
        """
        items = []
        for span in sorted(spans, key=lambda span: (span.start_token, span.end_token)):
            key_start, key_end = key_span(span.start_token, span.end_token)
            start, end = to_original(origins, utf16, *to_analysis(offsets, key_start, key_end))
            candidates = [
                {"name": usage.name, "review_status": _review_status(span.pattern, usage)}
                for _, usage in span.candidates
            ]
            items.append({"start": start, "end": end, "candidates": candidates})
        return items

    def analyze_and_save():
        """LLM 결과를 나오는 대로 낸다. 번역을 검증해 먼저 내고, 문법·단어까지 검증해 저장한
        뒤 이어 낸다. 실패하면 BusinessError이고 어느 단계에서 실패해도 저장하지 않는다.
        """
        if previous is not None:
            yield previous
        if closed_spans or spans:
            # LLM을 부르기 전에 확정 구간과 판별 대상 구간(화면의 확인 중)부터 보낸다. 이 뒤
            # 실패는 error 이벤트로 알린다(#39, #44).
            yield {"type": "grammar", "grammar": closed_grammar(), "checking": checking()}
        translation_sent = False
        result = None
        for kind, value in client.analyze_stream(key_text, tokens, llm_spans, decided_spans):
            if kind == "translation":
                _validate_translation(value, numbers)
                translation_sent = True
                yield translation_event(value)
            else:
                result = value
        validated = _validate(result, numbers, len(morphs), is_vocabulary, spans)
        if not translation_sent:
            yield translation_event(validated["translation_ko"])
        # 거부될 응답이면 다시 묻지 않는다.
        reject_quotes(validated)
        # 다시 묻기는 번역을 보낸 뒤, 저장 트랜잭션 밖에서 한다.
        yield save(ask_again(prepare(validated)))

    # 이 요청의 LLM 호출(분석·다시 묻기·예문 다시 쓰기)은 한 클라이언트로 해서 요청 전체 마감
    # 시각을 함께 쓴다.
    client = llm.get_client()
    events = analyze_and_save()
    # 첫 이벤트(옛 결과가 있으면 previous, 확정·판별 대상 구간이 있으면 grammar, 없으면 번역)까지는
    # 응답을 시작하기 전이라, 그 전에 실패하면 다른 API 오류처럼 오류 핸들러가 상태 코드로 알린다.
    first = next(events)
    return StreamingHttpResponse(
        map(_ndjson, _errors_as_event(chain([first], events))), content_type=_NDJSON
    )
