from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.grammar.services import get_or_create_grammar
from apps.library.text import normalize_sentence
from core.models import GrammarMatch, SentenceAnalysis

from .exceptions import LLMAnalysisError


@transaction.atomic
def save_grammar_analysis(sentence, morphology, result, model):
    sentence = type(sentence).objects.select_for_update().get(pk=sentence.pk)
    cached = sentence.analyses.filter(model_name=model).first()
    if cached:
        return cached, True

    tokens = list(morphology.tokens.all())
    try:
        normalized_text = result["normalized_text"].strip()
        meaning_ko = result["meaning_ko"].strip()
        explanation = result["explanation"].strip()
        grammar_items = result["grammars"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise LLMAnalysisError("LLM 분석 형식이 올바르지 않습니다.") from exc
    if not normalized_text or not isinstance(grammar_items, list):
        raise LLMAnalysisError("LLM 분석 형식이 올바르지 않습니다.")

    matches = []
    for item in grammar_items:
        try:
            canonical_name = normalize_sentence(item["canonical_name_ja"])
            name_ko = item["name_ko"].strip()
            summary = item["summary"].strip()
            evidence = item["evidence"].strip()
            start = item["start_token"]
            end = item["end_token"]
            confidence = Decimal(str(item["confidence"])).quantize(Decimal("0.001"))
        except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise LLMAnalysisError("LLM 문법 분석 형식이 올바르지 않습니다.") from exc
        if (
            not canonical_name
            or not name_ko
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(tokens)
            or not Decimal("0") <= confidence <= Decimal("1")
        ):
            raise LLMAnalysisError("LLM 문법 분석 범위가 올바르지 않습니다.")

        grammar = get_or_create_grammar(canonical_name, name_ko, summary)
        matches.append((grammar, tokens[start].begin_offset, tokens[end - 1].end_offset, confidence, evidence))

    analysis = SentenceAnalysis.objects.create(
        sentence=sentence,
        meaning_ko=meaning_ko,
        explanation=explanation,
        model_name=model,
        raw_result=result,
    )
    GrammarMatch.objects.bulk_create(
        [
            GrammarMatch(
                analysis=analysis,
                grammar=grammar,
                begin_offset=begin,
                end_offset=end,
                confidence=confidence,
                evidence=evidence,
            )
            for grammar, begin, end, confidence, evidence in matches
        ]
    )
    return analysis, False
