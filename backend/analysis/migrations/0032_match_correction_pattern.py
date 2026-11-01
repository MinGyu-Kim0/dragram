"""정정을 자리와 매칭된 패턴으로 구분한다(PR #320 리뷰). 같은 자리에 여러 패턴이 걸리면
자리만으로는 어느 패턴의 정정인지 가를 수 없었다. 기존 정정은 그 자리 구간 중 정정 전·후 용법의
소속 패턴(회화체면 원형)과 맞는 구간이 하나면 그 패턴으로 채우고, 가를 수 없으면 지운다(운영
배포 전이라 관리자 정정뿐).
"""

import django.db.models.deletion
from django.db import migrations, models


def fill_pattern(apps, schema_editor):
    MatchCorrection = apps.get_model("analysis", "MatchCorrection")
    SpanMatch = apps.get_model("analysis", "SpanMatch")
    for correction in MatchCorrection.objects.all():
        owners = {
            usage.pattern_id
            for usage in (correction.before_usage, correction.after_usage)
            if usage is not None
        }
        patterns = {
            span.pattern_id
            for span in SpanMatch.objects.filter(
                analysis_id=correction.analysis_id,
                start_offset=correction.start_offset,
                end_offset=correction.end_offset,
                pattern__isnull=False,
            ).select_related("pattern")
            if not owners or (span.pattern.variant_of_id or span.pattern_id) in owners
        }
        if len(patterns) == 1:
            correction.pattern_id = patterns.pop()
            correction.save(update_fields=["pattern"])
        else:
            correction.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0031_my_example_highlight"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="matchcorrection",
            name="match_correction_place",
        ),
        migrations.AddField(
            model_name="matchcorrection",
            name="pattern",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="analysis.grammarpattern",
            ),
        ),
        migrations.RunPython(fill_pattern, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="matchcorrection",
            name="pattern",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="analysis.grammarpattern",
            ),
        ),
        migrations.AddConstraint(
            model_name="matchcorrection",
            constraint=models.UniqueConstraint(
                fields=("analysis", "start_offset", "end_offset", "pattern"),
                name="match_correction_place",
            ),
        ),
    ]
