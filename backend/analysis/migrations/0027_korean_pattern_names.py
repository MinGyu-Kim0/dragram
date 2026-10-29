from django.db import migrations

# 긴 것부터 바꾼다(形容動詞가 動詞보다, 代名詞가 名詞보다 먼저).
KOREAN = [
    ("形容動詞", "형용동사"),
    ("形容詞", "형용사"),
    ("代名詞", "대명사"),
    ("名詞", "명사"),
    ("助動詞", "조동사"),
    ("動詞", "동사"),
    ("普通形", "보통형"),
    ("辞書形", "사전형"),
    ("連用形", "연용형"),
    ("連体形", "연체형"),
    ("未然形", "미연형"),
    ("仮定形", "가정형"),
    ("命令形", "명령형"),
    ("意志形", "의지형"),
    ("可能形", "가능형"),
    ("語幹", "어간"),
    ("ます形", "ます형"),
    ("て形", "て형"),
    ("た形", "た형"),
    ("ない形", "ない형"),
]


def to_korean(apps, schema_editor):
    GrammarPattern = apps.get_model("analysis", "GrammarPattern")
    for pattern in GrammarPattern.objects.all():
        name = pattern.name
        for ja, ko in KOREAN:
            name = name.replace(ja, ko)
        if name != pattern.name:
            pattern.name = name
            pattern.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [("analysis", "0026_usage_log_withdrawn_key")]

    operations = [migrations.RunPython(to_korean, migrations.RunPython.noop)]
