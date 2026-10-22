from django.db import models


class SentenceAnalysis(models.Model):
    """공용 문장 분석. 원문은 저장하지 않고 키 텍스트 해시로만 찾는다(docs/schema/schema.md).

    지금 쓰는 칼럼만 둔다. 나머지 칼럼은 쓰는 티켓에서 일반 마이그레이션으로 더한다
    (design-decisions 32절 7).
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
    # 다시 분석해야 하는 분석. 영향 범위의 패턴·용법이 반려·반려 취소·승인 취소되거나 용법
    # 완결이 바뀌면 켠다(#38). 판 번호는 아직 두지 않는다.
    is_stale = models.BooleanField(default=False)
    # 위 사건마다 1 올린다. 분석 요청은 시작할 때 읽은 값이 저장 직전과 다르면 저장하지 않는다.
    generation = models.IntegerField(default=0)
    # 분석 당시 패턴 세트 버전. 매칭(candidate_spans) 직전에 읽은 값이고 낮추지 않는다. 지금
    # 버전보다 낮으면 조회할 때 로컬 매칭을 다시 돌린다(#41). 이 칸 전의 행은 0이다.
    matcher_version = models.IntegerField(default=0)
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

    class Register(models.TextChoices):
        STANDARD = "standard"
        COLLOQUIAL = "colloquial"

    name = models.CharField(max_length=255)
    # 형태소 조건(lemma|pos1|pos2|conj, 아무거나는 *)을 순서대로 이은 문자열의 SHA-256
    morpheme_key = models.CharField(max_length=64, unique=True)
    # [{text, should_match}]. LLM·관리자가 새로 쓴 예문만 둔다. 사용자 원문은 넣지 않는다.
    test_cases = models.JSONField(default=list)
    # 바뀌면 같은 트랜잭션에서 pattern_set_version을 올린다.
    is_active = models.BooleanField()
    status = models.CharField(max_length=30, choices=ReviewStatus.choices)
    # 용법 완결: 관리자가 용법이 하나뿐이라고 확인한 패턴(#38)
    usage_closed = models.BooleanField(default=False)
    # 회화체 패턴(ちゃう 등)은 관리자가 원형(てしまう 등)에 연결한다. 연결된 회화체는 자기 용법
    # 없이 원형의 용법을 쓴다. register는 연결할 때만 colloquial이 되고 해제해도 남는다(#63).
    register = models.CharField(max_length=20, choices=Register.choices, default=Register.STANDARD)
    variant_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, related_name="variants"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grammar_pattern"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(variant_of=models.F("id")),
                name="grammar_pattern_variant_not_self",
            ),
            models.CheckConstraint(
                condition=models.Q(variant_of__isnull=True) | models.Q(register="colloquial"),
                name="grammar_pattern_variant_is_colloquial",
            ),
        ]

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

    def __str__(self):
        return f"{self.pattern_id}#{self.seq}"


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
        # 문장만으로 해석이 갈린다. usage는 번역과 같은 주 용법, alternatives는 대안 해석(#40)
        DIVERGENT = "divergent"
        # 다시 물어도 판단하지 못했다. 정상적인 최종 판정이다(#40).
        UNRESOLVED = "unresolved"

    class DecidedBy(models.TextChoices):
        # 승인된 용법 완결 패턴의 단일 후보를 LLM 없이 확정(#39)
        SINGLE_USAGE = "single_usage"
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
    # 해석 갈림의 대안 [{usage_id, translation_ko}](후보 순서). 번역은 주 번역처럼 키 텍스트
    # 기준이다. 근거는 그 문장을 풀어 쓴 글이라 두지 않는다.
    alternatives = models.JSONField(null=True)

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
            # 해석 갈림은 주 용법과 대안이 있고, 미확정은 둘 다 없다. 그 밖에는 대안이 없다.
            models.CheckConstraint(
                condition=(
                    models.Q(state="divergent", usage__isnull=False, alternatives__isnull=False)
                    & ~models.Q(alternatives=[])
                )
                | models.Q(state="unresolved", usage__isnull=True, alternatives__isnull=True)
                | (
                    ~models.Q(state__in=["divergent", "unresolved"])
                    & models.Q(alternatives__isnull=True)
                ),
                name="span_match_alternatives_by_state",
            ),
            # 같은 자리의 같은 패턴은 한 번만 둔다(#41). 중복 카드가 남지 않게 하는 백스톱이다.
            models.UniqueConstraint(
                fields=["analysis", "pattern", "start_offset", "end_offset"],
                condition=models.Q(pattern__isnull=False),
                name="span_match_place_unique",
            ),
        ]

    def __str__(self):
        return f"{self.analysis_id} [{self.start_offset}, {self.end_offset}) {self.state}"


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

    def __str__(self):
        return str(self.version)
