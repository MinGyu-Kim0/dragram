"""분석 API 테스트 도우미."""

import json
import time
import uuid

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client

from accounts import tokens
from analysis.jmdict import to_hiragana
from analysis.models import ReviewStatus, SentenceAnalysis, Word, WordSense


class Analyzed:
    """분석 API 응답. 줄 단위 JSON 스트림이면 이벤트를 모두 읽어 둔다.

    json()은 이벤트를 예전 한 번 응답 모양으로 합친다. error 이벤트가 있으면
    {"error": 코드}다. 스트림을 열기 전에 난 실패는 상태 코드와 JSON 본문 그대로다.
    """

    def __init__(self, response):
        self.response = response
        self.status_code = response.status_code
        body = read_body(response).decode()
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


def saved_analyses():
    """결과까지 저장된 분석. 실패한 시도는 결과 없이 failed 행으로 남는다(#98)."""
    return SentenceAnalysis.objects.filter(word_spans__isnull=False)


def read_body(response):
    """응답 본문 전체. LLM 작업을 기다리는 스트림은 비동기라 끝까지 읽어 모은다(#98)."""
    if not response.streaming:
        return response.content
    if not response.is_async:
        return b"".join(response.streaming_content)

    async def read():
        return [chunk async for chunk in response.streaming_content]

    return b"".join(async_to_sync(read)())


def connected_client():
    """확장처럼 Bearer 토큰을 붙여 요청하는 클라이언트. 분석 API는 로그인해야 쓴다(#109)."""
    user, _ = get_user_model().objects.get_or_create(
        username="analyst", defaults={"email": "analyst@example.com"}
    )
    # 같은 세션이 발급한 이전 토큰은 지워지므로 클라이언트마다 세션을 따로 둔다.
    token = tokens.issue(user, uuid.uuid4().hex)
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


def analyze(client, text):
    return Analyzed(post(client, text))


def post(client, text):
    """응답을 읽지 않고 돌려준다. 스트림을 조금씩 읽는 테스트에 쓴다."""
    return client.post("/api/analyses/", {"text": text}, content_type="application/json")


def add_word(seq, kanji, kana, senses, restrictions=None, common=True, tags=("noun",)):
    """표본 단어. senses는 (영어 뜻 목록, 뜻 태그, applies_to)들이다."""
    word = Word.objects.create(
        dictionary_form=(kanji or kana)[0],
        reading=kana[0],
        forms=[*kanji, *kana],
        readings=list(dict.fromkeys(to_hiragana(k) for k in kana)),
        is_common=common,
        reading_restrictions=restrictions,
        pos="n",
        tags=list(tags),
        jmdict_seq=seq,
    )
    for index, (gloss, sense_tags, applies_to) in enumerate(senses, start=1):
        WordSense.objects.create(
            word=word,
            jmdict_sense_index=index,
            gloss_en=gloss,
            tags=list(sense_tags),
            applies_to=applies_to,
            sense_origin=WordSense.Origin.JMDICT,
            sense_status=ReviewStatus.APPROVED,
            meaning_status=WordSense.MeaningStatus.AI,
        )
    return word


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


def span_answer(span_id, verdict="usage", candidate_id=None, new_usage=None):
    return {
        "span_id": span_id,
        "verdict": verdict,
        "candidate_id": candidate_id,
        "new_usage": new_usage,
    }


def new_usage(
    usage_name="역접",
    explanation_ko="앞 내용과 반대되는 뒤 내용을 잇는다",
    example_ja="狭いながら快適だ",
):
    """미발견 구간에 더할 새 용법."""
    return {"usage_name": usage_name, "explanation_ko": explanation_ko, "example_ja": example_ja}


def wait_until_blocked():
    """다른 연결이 잠금을 기다릴 때까지 기다린다."""
    for _ in range(100):
        with connection.cursor() as cursor:
            # 트랜잭션 안에서는 통계 뷰를 처음 읽은 값으로 고정하므로 매번 비운다.
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
            if cursor.fetchone()[0]:
                return
        time.sleep(0.05)
    raise AssertionError("다른 연결이 잠금을 기다리지 않음")


def usage_rows(pattern):
    """패턴 변경 화면의 용법 인라인 칸. 화면이 보인 값을 그대로 돌려보낸다."""
    usages = list(pattern.usages.order_by("id"))
    data = {"usages-TOTAL_FORMS": len(usages), "usages-INITIAL_FORMS": len(usages)}
    for i, usage in enumerate(usages):
        data[f"usages-{i}-id"] = usage.pk
        data[f"usages-{i}-pattern"] = pattern.pk
        data[f"usages-{i}-explanation_ko"] = usage.explanation_ko
        data[f"usages-{i}-example_ja"] = usage.example_ja or ""
    return data


def pattern_form(pattern, **changes):
    return {
        "name": pattern.name,
        "test_cases": json.dumps(pattern.test_cases, ensure_ascii=False),
        # 체크박스는 꺼져 있으면 POST에 오지 않는다.
        **({"show_parts": "on"} if pattern.show_parts else {}),
        "morphemes-TOTAL_FORMS": "0",
        "morphemes-INITIAL_FORMS": "0",
        **usage_rows(pattern),
        **changes,
    }
