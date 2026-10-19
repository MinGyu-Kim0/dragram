import hashlib
import logging

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from analysis import llm
from analysis.models import SentenceAnalysis
from analysis.morphology import tokenize

logger = logging.getLogger(__name__)

NORMALIZE_VERSION = 1


def _analysis_failed():
    return Response({"error": "analysis_failed"}, status=502)


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _validate(result):
    """LLM 응답에서 쓸 값만 꺼낸다. 형식이 틀리면 None."""
    if not isinstance(result, dict) or not _is_text(result.get("translation_ko")):
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

    key_text = sentence
    sentence_hash = hashlib.sha256(key_text.encode()).hexdigest()
    cached = SentenceAnalysis.objects.filter(sentence_hash=sentence_hash).first()
    if cached:
        return Response({"translation_ko": cached.translation_ko})

    # 원문은 로그에 남기지 않는다.
    try:
        result = llm.get_client().analyze(sentence, tokenize(sentence))
    except Exception:
        logger.exception("LLM 호출 실패")
        return _analysis_failed()

    analysis = _validate(result)
    if analysis is None:
        logger.warning("LLM 응답 검증 실패")
        return _analysis_failed()

    # 같은 문장이 동시에 저장되면 먼저 들어간 행을 쓴다.
    saved, _ = SentenceAnalysis.objects.get_or_create(
        sentence_hash=sentence_hash,
        defaults={
            "normalize_version": NORMALIZE_VERSION,
            "normalized_length": len(key_text),
            "status": SentenceAnalysis.Status.COMPLETE,
            "translation_ko": analysis["translation_ko"],
        },
    )
    return Response({"translation_ko": saved.translation_ko})
