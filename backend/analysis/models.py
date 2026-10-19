from django.db import models


class SentenceAnalysis(models.Model):
    """공용 문장 분석. 원문은 저장하지 않고 키 텍스트 해시로만 찾는다(docs/schema/schema.md).

    테스트 단계용으로 필요한 칼럼만 둔다. 본 구현을 시작할 때 마이그레이션을 다시 만든다
    (design-decisions 28절 12).
    """

    class Status(models.TextChoices):
        COMPLETE = "complete"

    sentence_hash = models.CharField(max_length=64, unique=True)
    normalize_version = models.SmallIntegerField()
    normalized_length = models.IntegerField()
    status = models.CharField(max_length=30, choices=Status.choices)
    # 스키마가 NULL을 허용한다(자리표시자가 보존된 번역만 저장). 빈 문자열과 구분한다.
    translation_ko = models.TextField(null=True)  # noqa: DJ001
    # 테스트 단계 임시 칼럼(design-decisions 28절 12). LLM이 쓴 문법 항목
    # [{start, end, name, explanation_ko}]. 위치는 키 텍스트 코드포인트 기준 [start, end).
    # NULL은 문법을 받기 전에 저장된 행이라 다시 분석한다.
    draft_grammar = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sentence_analysis"

    def __str__(self):
        return self.sentence_hash[:12]
