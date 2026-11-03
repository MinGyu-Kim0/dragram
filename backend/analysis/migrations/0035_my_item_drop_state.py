"""옛 상태 칸을 지우고, 두 축 중 하나는 켜져 있게 한다(#362)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0034_my_item_split_state"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="myitem",
            name="state",
        ),
        migrations.AddConstraint(
            model_name="myitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("added", True), ("hidden", True), _connector="OR"),
                name="my_item_added_or_hidden",
            ),
        ),
    ]
