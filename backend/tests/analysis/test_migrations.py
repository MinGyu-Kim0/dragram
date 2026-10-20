"""마이그레이션: 문법이 들어 있던 기존 분석은 다시 분석하게 한다(#35)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("analysis", "0003_draft_analysis")]
AFTER = [("analysis", "0004_grammar_pattern")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


# 끝난 뒤 테이블을 비우므로, 마이그레이션이 넣은 행(pattern_set_version)을 되돌려 둔다.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_analysis_with_sentence_grammar_is_analyzed_again():
    old_apps = migrate(BEFORE)
    SentenceAnalysis = old_apps.get_model("analysis", "SentenceAnalysis")
    row = SentenceAnalysis.objects.create(
        sentence_hash="a" * 64,
        normalize_version=1,
        normalized_length=6,
        status="complete",
        translation_ko="번역",
        draft_analysis={
            "grammar": [{"start": 1, "end": 2, "name": "주제", "explanation_ko": "설명"}],
            "words": [],
        },
    )

    new_apps = migrate(AFTER)

    row = new_apps.get_model("analysis", "SentenceAnalysis").objects.get(pk=row.pk)
    assert row.draft_analysis is None
    # 번역은 그대로 둔다. draft_analysis가 NULL이면 다시 분석해 함께 채운다.
    assert row.translation_ko == "번역"
    version = new_apps.get_model("analysis", "PatternSetVersion").objects.get()
    assert (version.id, version.version) == (1, 0)
