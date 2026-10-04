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
