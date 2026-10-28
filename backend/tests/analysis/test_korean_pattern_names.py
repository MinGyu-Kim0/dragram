"""마이그레이션: 패턴 이름의 품사·활용형을 한글로 바꾼다."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("analysis", "0026_usage_log_withdrawn_key")]
AFTER = [("analysis", "0027_korean_pattern_names")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_word_classes_in_pattern_names_become_korean():
    old_apps = migrate(BEFORE)
    Pattern = old_apps.get_model("analysis", "GrammarPattern")
    names = ["名詞+で", "形容動詞+に", "動詞普通形+名詞", "ます形の過去", "ている"]
    for i, name in enumerate(names):
        Pattern.objects.create(name=name, morpheme_key=str(i), is_active=True, status="pending")

    new_apps = migrate(AFTER)

    got = new_apps.get_model("analysis", "GrammarPattern").objects.order_by("morpheme_key")
    assert [p.name for p in got] == [
        "명사+で",
        "형용동사+に",
        "동사보통형+명사",
        "ます형の過去",
        "ている",
    ]
