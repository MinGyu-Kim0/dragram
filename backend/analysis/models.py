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
    # 테스트 단계 임시 칼럼(design-decisions 28절 12). LLM이 쓴 단어 항목
    # {"words": [{start, end, lemma, reading, meaning_ko}]}. 문법은 span_match에 둔다(#35).
    # 위치는 키 텍스트 코드포인트 기준 [start, end). NULL은 이 모양을 받기 전에 저장된 행이라
    # 다시 분석한다.
    draft_analysis = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sentence_analysis"

    def __str__(self):
        return self.sentence_hash[:12]


class ReviewStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GrammarPattern(models.Model):
    """문법 패턴. 승인·용법 완결·회화체 칼럼은 그것을 쓰는 티켓에서 더한다(#35)."""

    name = models.CharField(max_length=255)
    # 형태소 조건(lemma|pos1|pos2|conj, 아무거나는 *)을 순서대로 이은 문자열의 SHA-256
    morpheme_key = models.CharField(max_length=64, unique=True)
    # [{text, should_match}]. LLM·관리자가 새로 쓴 예문만 둔다. 사용자 원문은 넣지 않는다.
    test_cases = models.JSONField(default=list)
    # 바뀌면 같은 트랜잭션에서 pattern_set_version을 올린다.
    is_active = models.BooleanField()
    status = models.CharField(max_length=30, choices=ReviewStatus.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grammar_pattern"

    def __str__(self):
        return self.name


class PatternMorpheme(models.Model):
    """패턴 형태소 하나의 조건. 칸이 NULL이면 아무거나다."""

    pattern = models.ForeignKey(GrammarPattern, on_delete=models.CASCADE, related_name="morphemes")
    seq = models.SmallIntegerField()
    lemma = models.CharField(max_length=255, null=True)  # noqa: DJ001
    pos1 = models.CharField(max_length=30, null=True)  # noqa: DJ001
    pos2 = models.CharField(max_length=30, null=True)  # noqa: DJ001
    conjugation_form = models.CharField(max_length=30, null=True)  # noqa: DJ001

    class Meta:
        db_table = "pattern_morpheme"
        constraints = [
            models.UniqueConstraint(fields=["pattern", "seq"], name="pattern_morpheme_seq_unique")
        ]


class GrammarUsage(models.Model):
    """용법. 설명은 용법마다 하나이고 모든 문장이 함께 쓴다(문장 기준 해설 없음)."""

    class Origin(models.TextChoices):
        LLM = "llm"
        ADMIN = "admin"

    pattern = models.ForeignKey(GrammarPattern, on_delete=models.PROTECT, related_name="usages")
    name = models.CharField(max_length=255)
    explanation_ko = models.TextField()
    # LLM·관리자가 새로 쓴 예문만 둔다. 사용자 원문은 넣지 않는다.
    example_ja = models.TextField(null=True)  # noqa: DJ001
    status = models.CharField(max_length=30, choices=ReviewStatus.choices)
    origin = models.CharField(max_length=30, choices=Origin.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "grammar_usage"
        constraints = [
            models.UniqueConstraint(fields=["pattern", "name"], name="grammar_usage_name_unique")
        ]

    def __str__(self):
        return self.name


class SpanMatch(models.Model):
    """문장 분석의 구간 하나. 위치는 키 텍스트 코드포인트 기준 [start, end)다.

    확정·미검수는 저장하지 않고 조회할 때 용법·패턴의 status로 정한다(ADR 0003).
    """

    class State(models.TextChoices):
        DECIDED = "decided"
        NOT_APPLICABLE = "not_applicable"
        UNFOUND = "unfound"

    class DecidedBy(models.TextChoices):
        LLM = "llm"

    analysis = models.ForeignKey(
        SentenceAnalysis, on_delete=models.CASCADE, related_name="span_matches"
    )
    # 미발견 구간에서 새 패턴 등록에 실패해 패턴이 없으면 NULL
    pattern = models.ForeignKey(GrammarPattern, on_delete=models.PROTECT, null=True)
    usage = models.ForeignKey(GrammarUsage, on_delete=models.PROTECT, null=True)
    start_offset = models.IntegerField()
    end_offset = models.IntegerField()
    state = models.CharField(max_length=30, choices=State.choices)
    decided_by = models.CharField(  # noqa: DJ001
        max_length=30, choices=DecidedBy.choices, null=True
    )
    # LLM에 준 후보 [{candidate_id, usage_id}]
    candidates = models.JSONField(null=True)

    class Meta:
        db_table = "span_match"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_offset__gte=0, start_offset__lt=models.F("end_offset")),
                name="span_match_offsets_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(state="decided") | models.Q(usage__isnull=False),
                name="span_match_decided_has_usage",
            ),
        ]


class PatternSetVersion(models.Model):
    """현재 패턴 세트 버전. 항상 id = 1인 한 행이다."""

    id = models.SmallIntegerField(primary_key=True)
    version = models.IntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pattern_set_version"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="pattern_set_version_single_row")
        ]
