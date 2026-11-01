"""분석한 문장의 원문을 남기지 않기(#322). 예전에는 분석할 때마다 user_sentence에 원문을 저장했다
(#93). 이제 원문은 분석하는 동안만 거치고, 사용자가 카드를 추가하며 고른 예문만 남는다
(test_my_items).
"""

import pytest
from django.apps import apps
from django.contrib import admin
from django.core import serializers

from analysis import patterns
from analysis.models import SentenceAnalysis, UserSentence
from tests.analysis.helpers import analyze, connected_client, new_pattern, span_answer

pytestmark = pytest.mark.django_db

# 토큰: 0 走っ / 1 て / 2 いる
TEIRU = new_pattern((1, "lemma"), (2, "lemma"))


def test_new_and_cached_analyses_leave_no_record(client, fake_llm):
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}

    analyze(client, "走っている")
    response = analyze(client, "走っている")
    analyze(connected_client("other"), " 走っている")

    assert response.types() == ["translation", "analysis"]
    assert not UserSentence.objects.exists()


def test_rematched_and_reanalyzed_sentences_leave_no_record(client, fake_llm):
    # 토큰: 0 彼 / 1 が / 2 来 / 3 て / 4 いる
    fake_llm.response = {"translation_ko": "그가 와 있다"}
    analyze(client, "彼が来ている")
    fake_llm.response = {"translation_ko": "달리고 있다", "new_patterns": [TEIRU]}
    analyze(client, "走っている")
    fake_llm.rematch_response = {"spans": [span_answer(0, "usage", 1)]}
    analyze(client, "彼が来ている")
    patterns.raise_pattern_set_version()
    analyze(client, "走っている")
    SentenceAnalysis.objects.update(is_stale=True)
    analyze(client, "走っている")

    assert len(fake_llm.rematch_requests) == 1
    assert not UserSentence.objects.exists()


def test_old_records_are_not_in_django_admin():
    assert not admin.site.is_registered(UserSentence)


def test_original_is_stored_nowhere(client, fake_llm):
    # 원문 그대로가 키 텍스트가 되지 않게 감싼다. 예문은 LLM이 새로 쓴 문장이다.
    original = "「西山さんは走っている」"
    fake_llm.response = {
        "translation_ko": "그 사람은 달리고 있다",
        "new_patterns": [new_pattern((5, "lemma"), (6, "lemma"))],
        "name_spans": [{"token_ids": [1], "type": "person"}],
    }

    analyze(client, original)

    for model in apps.get_models():
        dumped = serializers.serialize("json", model.objects.all())
        assert original not in dumped, model
        assert "西山さんは走っている" not in dumped, model
