"""패턴 세트 버전이 오른 뒤 캐시 문장을 다시 매칭하기(#41)."""

import threading
import time

import pytest
from django.db import IntegrityError, connection, transaction
from django.test import Client

from analysis.models import PatternSetVersion, SentenceAnalysis, SpanMatch
from tests.analysis.helpers import analyze, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
KITEIRU = "彼が来ている"
# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))
# 토큰: 0 雨 / 1 が / 2 降る
GA = new_pattern(
    (1, "lemma"),
    pattern_name="が",
    usage_name="주격",
    explanation_ko="동작이나 상태의 주체를 나타낸다",
    example_ja="猫が鳴く",
)


def register(fake_llm, sentence, proposal, translation="번역"):
    """다른 문장을 분석해 새 패턴을 등록·활성화한다(패턴 세트 버전이 1 오른다)."""
    mine = fake_llm.response
    fake_llm.response = {"translation_ko": translation, "new_patterns": [proposal]}
    analyze(Client(), sentence)
    fake_llm.response = mine


def version():
    return PatternSetVersion.objects.get().version


def stored(sentence_text=KITEIRU):
    return SentenceAnalysis.objects.latest("id")


def test_analysis_records_the_pattern_set_version_read_before_matching(client, fake_llm):
    register(fake_llm, "走っている", TEIRU)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}
    # LLM을 기다리는 사이 다른 패턴이 활성화된다.
    fake_llm.before_respond = lambda: register(fake_llm, "雨が降る", GA)

    analyze(client, KITEIRU)

    assert version() == 2
    assert stored().matcher_version == 1


def test_stale_analysis_replaced_records_the_version_read_before_matching(client, fake_llm):
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, KITEIRU)
    register(fake_llm, "走っている", TEIRU)
    SentenceAnalysis.objects.filter(translation_ko="그가 와 있다").update(is_stale=True)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}

    analyze(client, KITEIRU)

    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    assert (analysis.is_stale, analysis.matcher_version) == (False, 1)


def test_same_span_cannot_be_stored_twice(client, fake_llm):
    register(fake_llm, "走っている", TEIRU)
    span = SpanMatch.objects.get()
    span.pk = None

    with pytest.raises(IntegrityError), transaction.atomic():
        span.save()


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


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_stale_replacement_conflicting_on_the_same_span_uses_the_other_result(fake_llm):
    register(fake_llm, "走っている", TEIRU)
    fake_llm.response = {"translation_ko": "그가 와 있다", "spans": [span_answer(0, "usage", 1)]}
    analyze(Client(), KITEIRU)
    analysis = SentenceAnalysis.objects.get(translation_ko="그가 와 있다")
    SentenceAnalysis.objects.filter(pk=analysis.pk).update(is_stale=True)
    fake_llm.response = {"translation_ko": "늦게 끝난 번역", "spans": [span_answer(0, "usage", 1)]}
    result = {}

    def other_request():
        try:
            result["response"] = analyze(Client(), KITEIRU)
        finally:
            connection.close()

    # 다른 요청이 같은 행을 교체하며 같은 구간을 넣고, 아직 커밋하지 않았다.
    with transaction.atomic():
        span = analysis.span_matches.get()
        analysis.span_matches.all().delete()
        span.pk = None
        span.save()
        thread = threading.Thread(target=other_request)
        thread.start()
        wait_until_blocked()
        SentenceAnalysis.objects.filter(pk=analysis.pk).update(
            is_stale=False, translation_ko="먼저 저장된 번역"
        )
    thread.join()

    assert result["response"].json()["translation_ko"] == "먼저 저장된 번역"
    assert analysis.span_matches.count() == 1
