"""분석 API 테스트 도우미."""


def analyze(client, text):
    return client.post("/api/analyses/", {"text": text}, content_type="application/json")


def grammar_items(*token_ranges):
    return [
        {"start_token_id": start, "end_token_id": end, "name": "문법", "explanation_ko": "설명"}
        for start, end in token_ranges
    ]


def word_item(token_id=2, lemma="学生", reading="がくせい", meaning_ko="학생"):
    return {"token_id": token_id, "lemma": lemma, "reading": reading, "meaning_ko": meaning_ko}
