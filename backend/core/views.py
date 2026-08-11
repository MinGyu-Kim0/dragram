import logging
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Sentence, User, UserSentence
from .services import (
    LLMAnalysisError,
    LLMConfigurationError,
    analyze_grammar,
    create_morphology,
    normalize_sentence,
    save_grammar_analysis,
    sentence_hash,
)

logger = logging.getLogger(__name__)
JAPANESE_TEXT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
LOCAL_USERNAME = "local"


def serialize_analysis(saved, analysis):
    sentence = saved.sentence
    raw_result = analysis.raw_result if isinstance(analysis.raw_result, dict) else {}
    morphology = sentence.morphologies.order_by("-created_at").first()
    return {
        "sentence_id": sentence.pk,
        "text": sentence.text,
        "normalized_text": raw_result.get("normalized_text", sentence.normalized_text),
        "meaning_ko": analysis.meaning_ko,
        "explanation": analysis.explanation,
        "model": analysis.model_name,
        "source_url": saved.source_url,
        "source_title": saved.source_title,
        "analyzed_at": analysis.created_at,
        "vocabulary": [
            {
                "surface": token.surface,
                "normalized_form": token.normalized_form,
                "dictionary_form": token.dictionary_form,
                "reading_form": token.reading_form,
                "part_of_speech": [
                    value
                    for value in (token.pos1, token.pos2, token.pos3, token.pos4, token.pos5, token.pos6)
                    if value
                ],
                "begin_offset": token.begin_offset,
                "end_offset": token.end_offset,
            }
            for token in morphology.tokens.all()
            if token.pos1 != "補助記号"
        ]
        if morphology
        else [],
        "grammars": [
            {
                "name_ja": match.grammar.name_ja,
                "name_ko": match.grammar.name_ko,
                "summary": match.grammar.summary,
                "begin_offset": match.begin_offset,
                "end_offset": match.end_offset,
                "confidence": float(match.confidence) if match.confidence is not None else None,
                "evidence": match.evidence,
            }
            for match in analysis.grammar_matches.all()
        ],
    }


def local_user():
    return User.objects.get_or_create(username=LOCAL_USERNAME)[0]


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([AllowAny])
def list_sentences(request):
    saved_sentences = UserSentence.objects.filter(user=local_user()).select_related("sentence").prefetch_related(
        "sentence__morphologies__tokens",
        "sentence__analyses__grammar_matches__grammar",
    )
    results = []
    for saved in saved_sentences.order_by("-updated_at"):
        analysis = max(saved.sentence.analyses.all(), key=lambda item: item.updated_at, default=None)
        if analysis:
            results.append(serialize_analysis(saved, analysis))
    return Response({"sentences": results})


@api_view(["POST"])
@permission_classes([AllowAny])
def analyze_sentence(request):
    text = request.data.get("text", "")
    source_url = request.data.get("source_url", "")
    source_title = request.data.get("source_title", "")
    model = request.data.get("model", settings.OPENAI_MODEL)
    if not all(isinstance(value, str) for value in (text, source_url, source_title, model)):
        return Response({"detail": "문장, 출처와 모델은 문자열이어야 합니다."}, status=400)
    if model not in settings.OPENAI_MODELS:
        return Response({"detail": "지원하지 않는 모델입니다."}, status=400)

    normalized = normalize_sentence(text)
    if not normalized or len(normalized) > 1000:
        return Response({"detail": "1자 이상 1000자 이하의 문장을 선택하세요."}, status=400)
    if not JAPANESE_TEXT.search(normalized):
        return Response({"detail": "일본어 문장을 선택하세요."}, status=400)
    if len(source_url) > 2000 or len(source_title) > 500:
        return Response({"detail": "출처 정보가 너무 깁니다."}, status=400)
    if source_url:
        try:
            URLValidator(schemes=["http", "https"])(source_url)
        except ValidationError:
            return Response({"detail": "출처 URL이 올바르지 않습니다."}, status=400)

    sentence, _ = Sentence.objects.get_or_create(
        text_hash=sentence_hash(normalized),
        defaults={"text": text.strip(), "normalized_text": normalized},
    )
    morphology = create_morphology(sentence)
    analysis = sentence.analyses.filter(model_name=model).first()
    cached = analysis is not None
    if analysis is None:
        try:
            result = analyze_grammar(sentence.normalized_text, morphology, model)
            analysis, cached = save_grammar_analysis(sentence, morphology, result, model)
        except LLMConfigurationError as exc:
            return Response({"detail": str(exc)}, status=503)
        except LLMAnalysisError:
            logger.exception("Japanese grammar analysis failed for sentence %s", sentence.pk)
            return Response({"detail": "문법 분석에 실패했습니다. 잠시 후 다시 시도하세요."}, status=502)

    saved, _ = UserSentence.objects.update_or_create(
        user=local_user(),
        sentence=sentence,
        defaults={"source_url": source_url, "source_title": source_title},
    )
    payload = serialize_analysis(saved, analysis)
    payload["cached"] = cached
    return Response(payload)
