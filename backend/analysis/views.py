import hashlib
import logging

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from analysis import llm
from analysis.models import SentenceAnalysis
from analysis.morphology import morpheme_spans
from analysis.normalize import (
    NORMALIZE_VERSION,
    analysis_text,
    has_all_placeholders,
    key_pieces,
    restore_numbers,
)

logger = logging.getLogger(__name__)


def _analysis_failed():
    return Response({"error": "analysis_failed"}, status=502)


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _validate(result, numbers):
    """LLM 응답에서 쓸 값만 꺼낸다. 형식이 틀리거나 자리표시자가 맞지 않으면 None."""
    if not isinstance(result, dict) or not _is_text(result.get("translation_ko")):
        return None
    # 자리표시자가 맞지 않는 번역은 숫자가 틀렸을 수 있어 보여주지도 저장하지도 않는다.
    if not has_all_placeholders(result["translation_ko"], numbers):
        return None
    return {"translation_ko": result["translation_ko"]}


# 테스트 단계라 로그인 없이 연다. 로그인 없는 사용을 정식으로 허용한다는 결정은 아니다(#10).
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def analyze(request):
    sentence = request.data.get("text") if isinstance(request.data, dict) else None
    if not _is_text(sentence):
        return Response({"error": "text_required"}, status=400)

    text_to_analyze = analysis_text(sentence)
    if not text_to_analyze:
        return Response({"error": "text_required"}, status=400)
    pieces, numbers = key_pieces(text_to_analyze)
    key_text = "".join(pieces)
    sentence_hash = hashlib.sha256(key_text.encode()).hexdigest()
    cached = SentenceAnalysis.objects.filter(sentence_hash=sentence_hash).first()
    if cached:
        return Response({"translation_ko": restore_numbers(cached.translation_ko, numbers)})

    # 형태소 분석은 숫자가 그대로인 분석 텍스트로 하고, LLM에는 키 텍스트 기준 표층형을
    # 보낸다. 원문 숫자는 LLM에 가지 않는다.
    tokens = [
        {"id": i, "surface": "".join(pieces[begin:end])}
        for i, (begin, end) in enumerate(morpheme_spans(text_to_analyze))
    ]
    # 원문은 로그에 남기지 않는다.
    try:
        result = llm.get_client().analyze(key_text, tokens)
    except Exception:
        logger.exception("LLM 호출 실패")
        return _analysis_failed()

    validated = _validate(result, numbers)
    if validated is None:
        logger.warning("LLM 응답 검증 실패")
        return _analysis_failed()

    # 같은 문장이 동시에 저장되면 먼저 들어간 행을 쓴다.
    saved, _ = SentenceAnalysis.objects.get_or_create(
        sentence_hash=sentence_hash,
        defaults={
            "normalize_version": NORMALIZE_VERSION,
            "normalized_length": len(key_text),
            "status": SentenceAnalysis.Status.COMPLETE,
            "translation_ko": validated["translation_ko"],
        },
    )
    return Response({"translation_ko": restore_numbers(saved.translation_ko, numbers)})
