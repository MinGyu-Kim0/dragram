from django.db import migrations, models


class Migration(migrations.Migration):
    """문법만 담던 임시 칼럼을 문법·단어를 함께 담는 칼럼 하나로 바꾼다(#10, #15).

    기존 행에는 단어가 없으므로 값을 옮기지 않는다. 새 칼럼이 NULL인 행은 다음 요청 때
    다시 분석된다(테스트 단계 로컬 DB뿐이다).
    """

    dependencies = [
        ("analysis", "0002_sentenceanalysis_draft_grammar"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="sentenceanalysis",
            name="draft_grammar",
        ),
        migrations.AddField(
            model_name="sentenceanalysis",
            name="draft_analysis",
            field=models.JSONField(null=True),
        ),
    ]
