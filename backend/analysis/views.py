import hashlib
import logging

from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from analysis import llm
from analysis.models import SentenceAnalysis
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

logger = logging.getLogger(__name__)


def _analysis_failed():
    return Response({"error": "analysis_failed"}, status=502)


def _numbers_before_particle(text, morphs):
    """원문에서 바로 뒤에 조사(助詞)가 오는 숫자의 자리표시자 번호."""
    particle_starts = {begin for begin, _, pos in morphs if pos == "助詞"}
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


def _validate_grammar(grammar, numbers, token_count):
    """LLM이 고른 문법 항목을 검증한다. 하나라도 틀리면 None."""
    if not isinstance(grammar, list):
        return None
    items = []
    for item in grammar:
        if not isinstance(item, dict):
            return None
        start, end = item.get("start_token_id"), item.get("end_token_id")
        if not (_is_token_id(start, token_count) and _is_token_id(end, token_count)):
            return None
        if start > end:
            return None
        name, explanation = item.get("name"), item.get("explanation_ko")
        if not (_is_text(name) and _is_text(explanation)):
            return None
        # 이름·설명도 응답할 때 숫자를 되돌리므로 없는 번호의 자리표시자는 받지 않는다.
        if not all(has_only_known_placeholders(t, numbers) for t in (name, explanation)):
            return None
        items.append(
            {"start_token": start, "end_token": end, "name": name, "explanation_ko": explanation}
        )
    return items


def _validate(result, numbers, token_count):
    """LLM 응답에서 쓸 값만 꺼낸다. 형식이 틀리거나 자리표시자가 맞지 않으면 None."""
    if not isinstance(result, dict) or not _is_text(result.get("translation_ko")):
        return None
    # 자리표시자가 맞지 않는 번역은 숫자가 틀렸을 수 있어 보여주지도 저장하지도 않는다.
    if not has_all_placeholders(result["translation_ko"], numbers):
        return None
    grammar = _validate_grammar(result.get("grammar"), numbers, token_count)
    if grammar is None:
        return None
    return {"translation_ko": result["translation_ko"], "grammar": grammar}


def _stored_grammar(grammar, morphs, offsets):
    """토큰 ID로 고른 문법 항목을 키 텍스트 구간으로 바꿔 저장할 모양으로 만든다."""
    stored = []
    for item in grammar:
        begin = morphs[item["start_token"]][0]
        end = morphs[item["end_token"]][1]
        key_start, key_end = to_key(offsets, begin, end)
        stored.append(
            {
                "start": key_start,
                "end": key_end,
                "name": item["name"],
                "explanation_ko": item["explanation_ko"],
            }
        )
    return stored


def _quotes_whole_sentence(grammar, key_text, token_count):
    """이름이나 설명이 문장 전체(키 텍스트)를 인용했는가.

    문장이 형태소 하나(です 등)면 그 문법 토큰을 인용하는 것과 같고 원문을 알아볼 정보도
    없어 허용한다. 토큰이 여럿이면 구간이 문장 전체여도 원문을 옮긴 것이다.
    """
    if token_count == 1:
        return False
    return any(
        key_text in text for item in grammar for text in (item["name"], item["explanation_ko"])
    )


def _grammar_response(stored, offsets, origins, utf16, restore):
    """저장된 문법 항목의 키 텍스트 구간을 이 요청 원문의 UTF-16 위치로 바꾼다.

    같은 분석을 표기가 다른 원문(앞 공백, 괄호, 숫자 자릿수 등)이 함께 쓰므로, 요청마다
    그 원문 기준으로 다시 계산한다. 이름·설명의 자리표시자도 번역처럼 이 원문의 숫자로
    되돌린다(restore).
    """
    grammar = []
    for item in stored:
        start, end = to_original(origins, utf16, *to_analysis(offsets, item["start"], item["end"]))
        grammar.append(
            {
                "start": start,
                "end": end,
                "name": restore(item["name"]),
                "explanation_ko": restore(item["explanation_ko"]),
                # 이 단위의 문법은 모두 LLM이 썼고 아직 아무도 검수하지 않았다.
                "review_status": "pending",
            }
        )
    return grammar


# 테스트 단계라 로그인 없이 연다. 로그인 없는 사용을 정식으로 허용한다는 결정은 아니다(#10).
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def analyze(request):
    sentence = request.data.get("text") if isinstance(request.data, dict) else None
    if not _is_text(sentence):
        return Response({"error": "text_required"}, status=400)

    text_to_analyze, origins = analysis_text(sentence)
    if not text_to_analyze:
        return Response({"error": "text_required"}, status=400)
    pieces, numbers = key_pieces(text_to_analyze)
    key_text = "".join(pieces)
    sentence_hash = hashlib.sha256(key_text.encode()).hexdigest()

    # 형태소 분석은 숫자가 그대로인 분석 텍스트로 한다. 숫자 뒤 조사 교정에 쓰므로 캐시를
    # 재사용할 때도 한다. 원문은 로그에 남기지 않는다.
    try:
        morphs = morphemes(text_to_analyze)
    except Exception:
        # SudachiPy가 나누지 못하는 입력(49,149바이트 초과 등)
        logger.exception("형태소 분석 실패")
        return _analysis_failed()
    particle_numbers = _numbers_before_particle(text_to_analyze, morphs)

    offsets = key_offsets(pieces)
    utf16 = utf16_offsets(sentence)

    def restore(text):
        return restore_numbers(text, numbers, particle_numbers)

    def respond(saved):
        return Response(
            {
                "translation_ko": restore(saved.translation_ko),
                "grammar": _grammar_response(saved.draft_grammar, offsets, origins, utf16, restore),
            }
        )

    # 문법을 받기 전에 저장된 행(draft_grammar가 NULL)은 다시 분석한다.
    cached = SentenceAnalysis.objects.filter(
        sentence_hash=sentence_hash, draft_grammar__isnull=False
    ).first()
    if cached:
        return respond(cached)

    # LLM에는 키 텍스트 기준 표층형을 보내 원문 숫자가 가지 않게 한다.
    tokens = [
        {"id": i, "surface": "".join(pieces[begin:end])} for i, (begin, end, _) in enumerate(morphs)
    ]
    try:
        result = llm.get_client().analyze(key_text, tokens)
    except Exception:
        logger.exception("LLM 호출 실패")
        return _analysis_failed()

    validated = _validate(result, numbers, len(morphs))
    if validated is None:
        logger.warning("LLM 응답 검증 실패")
        return _analysis_failed()
    grammar = _stored_grammar(validated["grammar"], morphs, offsets)
    if _quotes_whole_sentence(grammar, key_text, len(morphs)):
        # 이름·설명은 공용 테이블에 들어가므로 원문을 통째로 옮긴 결과는 저장하지 않는다.
        logger.warning("LLM 문법 설명이 문장 전체를 인용함")
        return _analysis_failed()

    # 같은 문장이 동시에 저장되면 먼저 들어간 행을 쓴다.
    saved, created = SentenceAnalysis.objects.get_or_create(
        sentence_hash=sentence_hash,
        defaults={
            "normalize_version": NORMALIZE_VERSION,
            "normalized_length": len(key_text),
            "status": SentenceAnalysis.Status.COMPLETE,
            "translation_ko": validated["translation_ko"],
            "draft_grammar": grammar,
        },
    )
    if not created and saved.draft_grammar is None:
        # 문법을 받기 전에 저장된 행이면 이번 결과로 채운다. 그사이 다른 요청이 먼저
        # 채웠으면 그 값을 쓴다(NULL일 때만 갱신).
        SentenceAnalysis.objects.filter(pk=saved.pk, draft_grammar__isnull=True).update(
            translation_ko=validated["translation_ko"],
            draft_grammar=grammar,
            updated_at=timezone.now(),
        )
        saved.refresh_from_db()
    return respond(saved)
