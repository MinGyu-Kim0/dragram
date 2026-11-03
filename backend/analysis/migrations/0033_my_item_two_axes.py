"""내 일본어 항목에 추가·숨김 두 축을 더한다(#362). 옮기기는 0034, 옛 상태 칸 지우기는 0035다."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0032_match_correction_pattern"),
    ]

    operations = [
        migrations.AddField(
            model_name="myitem",
            name="added",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="myitem",
            name="hidden",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="myitem",
            name="state",
            field=models.CharField(max_length=30, null=True),
        ),
    ]
