"""분석 API 테스트 도우미."""

import json


class Analyzed:
    """분석 API 응답. 줄 단위 JSON 스트림이면 이벤트를 모두 읽어 둔다.

    json()은 이벤트를 예전 한 번 응답 모양으로 합친다. error 이벤트가 있으면
    {"error": 코드}다. 스트림을 열기 전에 난 실패는 상태 코드와 JSON 본문 그대로다.
    """

    def __init__(self, response):
        self.response = response
        self.status_code = response.status_code
        body = (
            b"".join(response.streaming_content) if response.streaming else response.content
        ).decode()
        if response["Content-Type"] == "application/x-ndjson":
            self.events = [json.loads(line) for line in body.splitlines()]
            self._json = None
        else:
            self.events = None
            self._json = json.loads(body)

    def json(self):
        if self.events is None:
            return self._json
        for event in self.events:
            if event["type"] == "error":
                return {"error": event["error"]}
        merged = {}
        for event in self.events:
            merged.update({key: value for key, value in event.items() if key != "type"})
        return merged

    def types(self):
        return [event["type"] for event in self.events]


def analyze(client, text):
    return Analyzed(post(client, text))


def post(client, text):
    """응답을 읽지 않고 돌려준다. 스트림을 조금씩 읽는 테스트에 쓴다."""
    return client.post("/api/analyses/", {"text": text}, content_type="application/json")


def word_item(token_id=2, lemma="学生", reading="がくせい", meaning_ko="학생"):
    return {"token_id": token_id, "lemma": lemma, "reading": reading, "meaning_ko": meaning_ko}


def new_pattern(
    *tokens,
    pattern_name="ている",
    usage_name="진행",
    explanation_ko="동작이 이어지고 있음을 나타낸다",
    example_ja="雨が降っている",
):
    """새 구문 제안. tokens는 (토큰 ID, 표시) 쌍이다."""
    return {
        "tokens": [{"token_id": token_id, "fix": fix} for token_id, fix in tokens],
        "pattern_name": pattern_name,
        "usage_name": usage_name,
        "explanation_ko": explanation_ko,
        "example_ja": example_ja,
    }


def span_answer(span_id, verdict="usage", candidate_id=None):
    return {"span_id": span_id, "verdict": verdict, "candidate_id": candidate_id}
