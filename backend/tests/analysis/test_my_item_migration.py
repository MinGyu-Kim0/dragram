"""마이그레이션: 내 일본어 항목의 상태 칸을 추가·숨김 두 축으로 나눈다(#362)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("analysis", "0032_match_correction_pattern")]
AFTER = [("analysis", "0035_my_item_drop_state")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_hidden_items_with_examples_become_added_and_hidden():
    old_apps = migrate(BEFORE)
    User = old_apps.get_model("accounts", "User")
    Word = old_apps.get_model("analysis", "Word")
    WordSense = old_apps.get_model("analysis", "WordSense")
    MyItem = old_apps.get_model("analysis", "MyItem")
    MyExample = old_apps.get_model("analysis", "MyExample")
    user = User.objects.create(username="me")
    word = Word.objects.create(
        dictionary_form="走る",
        reading="はしる",
        forms=["走る"],
        readings=["はしる"],
        is_common=True,
        pos="v",
        tags=[],
    )
    senses = [
        WordSense.objects.create(
            word=word,
            jmdict_sense_index=index,
            gloss_en=["to run"],
            tags=[],
            sense_origin="jmdict",
            sense_status="approved",
            meaning_status="ai",
        )
        for index in (1, 2, 3)
    ]
    added = MyItem.objects.create(user=user, sense=senses[0], state="added")
    hidden = MyItem.objects.create(user=user, sense=senses[1], state="hidden")
    # 추가한 뒤 숨겨 예문이 남은 항목(PR #360)
    hidden_after_adding = MyItem.objects.create(user=user, sense=senses[2], state="hidden")
    MyExample.objects.create(
        item=hidden_after_adding, original_hash="a" * 64, original_text="走った。"
    )

    new_apps = migrate(AFTER)

    rows = new_apps.get_model("analysis", "MyItem").objects
    assert [(r.added, r.hidden) for r in rows.order_by("pk")] == [
        (True, False),
        (False, True),
        (True, True),
    ]
    assert {r.pk for r in rows.all()} == {added.pk, hidden.pk, hidden_after_adding.pk}
    # 뒤 테스트가 쓰도록 최신 마이그레이션까지 되돌려 놓는다.
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
