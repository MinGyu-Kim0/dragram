"""예전에 분석할 때마다 자동 저장한 문장 원문을 지운다(#321, #325).

원문을 더는 저장하지 않으므로, 처리방침(2026-11-02판)이 안내한 대로 남은 기록을 배포할 때 지운다.
되돌리지 않는다. 테이블은 남긴다(없앨지는 따로 정한다).
"""

from django.db import migrations


def delete_old_records(apps, schema_editor):
    apps.get_model("analysis", "UserSentence").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("analysis", "0029_my_item")]

    operations = [migrations.RunPython(delete_old_records, migrations.RunPython.noop)]
