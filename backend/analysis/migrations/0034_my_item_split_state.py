"""내 일본어 항목의 상태 칸을 추가·숨김 두 축으로 옮긴다(#362).

added → 추가. hidden → 숨김이다. 예문은 추가된 항목에만 생기므로 예문이 있는 hidden 행은
추가했다가 숨긴 것으로 본다(PR #360부터 추가한 카드를 숨겨도 예문이 남는다).
"""

from django.db import migrations
from django.db.models import Exists, OuterRef


def split_state(apps, schema_editor):
    MyItem = apps.get_model("analysis", "MyItem")
    MyExample = apps.get_model("analysis", "MyExample")
    MyItem.objects.filter(state="added").update(added=True)
    MyItem.objects.filter(state="hidden").update(hidden=True)
    MyItem.objects.filter(state="hidden").filter(
        Exists(MyExample.objects.filter(item=OuterRef("pk")))
    ).update(added=True)


def join_state(apps, schema_editor):
    # 되돌리면 숨김이 추가보다 앞선다(옛 확장이 숨긴 카드로 보이던 대로).
    MyItem = apps.get_model("analysis", "MyItem")
    MyItem.objects.filter(hidden=True).update(state="hidden")
    MyItem.objects.filter(hidden=False).update(state="added")


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0033_my_item_two_axes"),
    ]

    operations = [
        migrations.RunPython(split_state, join_state),
    ]
