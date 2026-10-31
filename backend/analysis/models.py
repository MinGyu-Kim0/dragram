from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models


class SentenceAnalysis(models.Model):
    """공용 문장 분석. 원문은 저장하지 않고 키 텍스트 해시로만 찾는다(docs/schema/schema.md).

    지금 쓰는 칼럼만 둔다. 나머지 칼럼은 쓰는 티켓에서 일반 마이그레이션으로 더한다
    (design-decisions 32절 7).
    """

    class Status(models.TextChoices):
        # 작업자가 LLM 분석을 하고 있다. 조건부 UPDATE로 이 상태를 선점한 요청만 작업을 넣는다(#98).
        PROCESSING = "processing"
        COMPLETE = "complete"
        # 마지막 작업이 실패했다. 다음 요청이 다시 선점한다.
        FAILED = "failed"

    sentence_hash = models.CharField(max_length=64, unique=True)
    normalize_version = models.SmallIntegerField()
    normalized_length = models.IntegerField()
    status = models.CharField(max_length=30, choices=Status.choices)
    # 마지막으로 선점한 때. 멈춘 작업을 찾는 기준이다(#99).
    processing_started_at = models.DateTimeField(null=True)
    # 스키마가 NULL을 허용한다(자리표시자가 보존된 번역만 저장). 빈 문자열과 구분한다.
    translation_ko = models.TextField(null=True)  # noqa: DJ001
    # 문장 단어의 위치와 고른 뜻: [{start, end, sense_id}](#96). 위치는 키 텍스트 코드포인트 기준
    # [start, end)이고, 같은 단어가 두 번 나오면 위치마다 하나씩 둔다. 공용 테이블이라 위치와
    # ID만 둔다. NULL은 이 칸을 받기 전에 저장된 행이라 다시 분석한다.
    word_spans = models.JSONField(null=True)
    # 처리 중 작업이 검증해 먼저 저장한 번역(자리표시자 형태). 늦게 온 요청이 소식을 놓쳤어도
    # 번역을 먼저 보이게 한다. stale 재분석 중에도 translation_ko(옛 결과)를 덮지 않도록 따로 두고,
    # 작업이 끝나면 비운다(#98).
    processing_translation_ko = models.TextField(null=True)  # noqa: DJ001
    # 이름 구간: [{start, end, type}](#140). 위치는 word_spans와 같은 키 텍스트 기준이고, 새 문장 첫
    # LLM 요청이 판단한다. NULL은 이 칸 전에 저장된 행(판단 안 함)이고 다시 분석하지 않는다.
    # []는 이름이 없다는 판단이다.
    name_spans = models.JSONField(null=True)
    # word_spans의 뜻 ID를 중복 없이 모은 값(ADR 0002, 내 일본어 계산용). word_spans와 함께 쓴다.
    sense_ids = ArrayField(models.BigIntegerField(), null=True)
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
        indexes = [GinIndex(fields=["sense_ids"], name="analysis_sense_ids_gin")]

    def __str__(self):
        return self.sentence_hash[:12]


class ReviewStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


CONNECTION_FORM_LENGTH = 255


class GrammarPattern(models.Model):
    """문법 패턴. 승인·용법 완결·회화체 칼럼은 그것을 쓰는 티켓에서 더한다(#35)."""

    class Register(models.TextChoices):
        STANDARD = "standard"
        COLLOQUIAL = "colloquial"

    name = models.CharField(max_length=255)
    # 문장별 설명이 아닌 패턴의 접속 형태. LLM이 채운 값은 따로 검수한다(#229).
    connection_form = models.CharField(  # noqa: DJ001
        "접속 형태", max_length=CONNECTION_FORM_LENGTH, null=True, blank=True
    )
    connection_filled = models.BooleanField(default=False)
    connection_status = models.CharField(  # noqa: DJ001
        max_length=30, choices=ReviewStatus.choices, null=True
    )
    connection_started_at = models.DateTimeField(null=True)
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
    # 이 패턴 구간 안의 구성 문법을 화면에 하위 박스로 보일지(#65). 조회할 때만 읽는 표시 칸이라
    # 바꿔도 stale·세대 번호·패턴 세트 버전을 건드리지 않는다.
    show_parts = models.BooleanField(default=True)
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


# 대응 표현 칸 길이. LLM 답이 넘으면 그 칸만 비운다(#152).
KOREAN_EQUIVALENT_LENGTH = 100


class FunctionTag(models.TextChoices):
    """용법의 기능 태그 허용 목록(#151). 이름은 화면 이름이고 확장도 같은 이름을 쓴다."""

    # 동사의 모양
    PASSIVE = "passive", "수동"
    CAUSATIVE = "causative", "사역"
    CAUSATIVE_PASSIVE = "causative_passive", "사역수동"
    POTENTIAL = "potential", "가능"
    HONORIFIC = "honorific", "존경"
    HUMBLE = "humble", "겸양"
    # 시제·상
    PAST = "past", "과거"
    PROGRESSIVE = "progressive", "진행"
    PERFECTIVE = "perfective", "완료"
    RESULTATIVE = "resultative", "결과 상태"
    # 말투
    POLITE = "polite", "정중"
    CASUAL = "casual", "회화체"
    # 판단·부정
    NEGATIVE = "negative", "부정"
    CONJECTURE = "conjecture", "추측"
    HEARSAY = "hearsay", "전문"
    OBLIGATION = "obligation", "당위"
    # 문장 연결
    CONDITIONAL = "conditional", "조건"
    CAUSE = "cause", "원인·이유"
    ADVERSATIVE = "adversative", "역접"
    PURPOSE = "purpose", "목적"
    LISTING = "listing", "나열"
    # 조사의 역할
    TOPIC = "topic", "주제"
    SUBJECT = "subject", "주어"
    OBJECT = "object", "목적어"
    TARGET = "target", "대상"
    PLACE = "place", "장소"
    TIME = "time", "시간"
    MEANS = "means", "수단"
    GOAL = "goal", "도달점"
    SOURCE = "source", "출발점"
    SCOPE = "scope", "범위"
    COMPARISON = "comparison", "비교"


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
    # 이 용법이 한국어로 주로 옮겨지는 표현(#152). 마땅한 대응이 없으면 NULL이다.
    korean_equivalent = models.CharField(  # noqa: DJ001
        max_length=KOREAN_EQUIVALENT_LENGTH, null=True, blank=True
    )
    # 대응 표현을 채운 적이 있는가. NULL이 '대응 없음'인지 '아직 안 채움'인지 가른다(fill_usages).
    korean_equivalent_filled = models.BooleanField(default=False)
    # 대응 표현의 검수 상태(pending·approved). 값이 없으면 NULL이다. 용법을 승인하면 함께
    # 승인되고, 승인된 용법에 LLM이 나중에 채운 값은 따로 승인할 때까지 미검수다(#152).
    korean_equivalent_status = models.CharField(  # noqa: DJ001
        max_length=30, choices=ReviewStatus.choices, null=True
    )
    # 기능 태그(FunctionTag 코드, 허용 목록 순서, #151). 대응 표현처럼 채움 여부와 검수 상태를
    # 따로 둔다. 상태는 태그가 없으면 NULL이다.
    function_tags = ArrayField(
        models.CharField(max_length=30, choices=FunctionTag.choices), default=list, blank=True
    )
    function_tags_filled = models.BooleanField(default=False)
    function_tags_status = models.CharField(  # noqa: DJ001
        max_length=30, choices=ReviewStatus.choices, null=True
    )
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


class UsageRule(models.Model):
    """판별 규칙: 한 패턴의 구간 앞뒤 형태소가 조건에 맞으면 그 구간을 정해진 용법으로 본다(#55).

    관리자가 admin에서 만든다. 승인된 규칙은 내용을 바꾸지 않으므로 판 번호를 두지 않는다.
    바꾸려면 폐기하고 새로 만든다. 판정 기록(span_match.rule)이 가리키므로 지우지 않는다.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        RETIRED = "retired"

    # 실제로 매칭된 패턴. 연결된 회화체면 용법은 원형의 것이다.
    pattern = models.ForeignKey(GrammarPattern, on_delete=models.PROTECT, related_name="rules")
    usage = models.ForeignKey(GrammarUsage, on_delete=models.PROTECT, related_name="rules")
    # [{position: -2|-1|1|2, lemma, pos1, pos2, pos3, conjugation_form}] (analysis.rules)
    condition = models.JSONField()
    # [{text, should_apply}]. 관리자가 새로 쓴 예문만 둔다. 사용자 원문은 넣지 않는다.
    test_cases = models.JSONField(default=list)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "usage_rule"

    def __str__(self):
        return f"{self.pattern_id} → {self.usage_id} #{self.pk}"


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
        # 승인된 판별 규칙으로 LLM 없이 확정(#55)
        RULE = "rule"
        LLM = "llm"
        # 관리자 정정(match_correction)을 적용했다(#221)
        ADMIN = "admin"

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
    # 판별 규칙으로 확정했으면 그 규칙(decided_by = rule일 때만, #55)
    rule = models.ForeignKey(UsageRule, on_delete=models.PROTECT, null=True)
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
            models.CheckConstraint(
                # decided_by가 NULL이면 첫 절이 NULL이 되어 통과하지 않게 IS NOT NULL을 둔다.
                condition=models.Q(decided_by__isnull=False, decided_by="rule", rule__isnull=False)
                | (~models.Q(decided_by="rule") & models.Q(rule__isnull=True)),
                name="span_match_rule_iff_decided_by_rule",
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


class MatchCorrection(models.Model):
    """관리자 매칭 정정(FR-A21, #221). 위치는 키 텍스트 코드포인트 기준 [start, end)다.

    재분석해도 덮어쓰지 않는다. 분석할 때 활성 정정이 LLM·DB 판정보다 먼저 적용된다.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "적용"
        SUSPENDED = "suspended", "멈춤"

    analysis = models.ForeignKey(
        SentenceAnalysis, on_delete=models.CASCADE, related_name="corrections"
    )
    start_offset = models.IntegerField()
    end_offset = models.IntegerField()
    before_usage = models.ForeignKey(
        GrammarUsage, on_delete=models.PROTECT, null=True, related_name="+"
    )
    # NULL이면 매칭 해제
    after_usage = models.ForeignKey(
        GrammarUsage, on_delete=models.PROTECT, null=True, related_name="+"
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE)
    # 정정한 관리자가 탈퇴해도 정정은 남는다(다른 관리자 칸과 같다).
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "match_correction"
        constraints = [
            models.UniqueConstraint(
                fields=["analysis", "start_offset", "end_offset"], name="match_correction_place"
            )
        ]

    def __str__(self):
        return f"{self.analysis_id} [{self.start_offset}, {self.end_offset})"


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


class UsageLog(models.Model):
    """분석 요청과 LLM 호출의 사용 기록(FR-A18). 원문은 저장하지 않는다(불변식).

    분석 요청마다 request 행 하나, LLM 호출마다 llm 행 하나를 남긴다. LLM 호출 기록은 분석
    저장이 되돌려져도 남도록 저장 트랜잭션 밖에서 바로 쓴다.
    """

    class Kind(models.TextChoices):
        REQUEST = "request"
        LLM = "llm"

    class Path(models.TextChoices):
        # 버전이 최신인 캐시 분석을 그대로 보냄
        CACHE = "cache"
        # 캐시 분석을 다시 매칭했고 LLM 없이 확정함
        DB = "db"
        # LLM을 부름(새 문장, stale 재분석, 재매칭 재판정)
        LLM = "llm"

    class Purpose(models.TextChoices):
        FIRST_RESPONSE = "first_response"
        REASK = "reask"
        EXAMPLE_REWRITE = "example_rewrite"
        REMATCH_JUDGE = "rematch_judge"
        WORD_GLOSS = "word_gloss"
        KANJI_GLOSS = "kanji_gloss"
        # 이미 있는 용법의 빈 칸(대응 표현)을 채움(#152). 사용자 요청이 아니라 user는 NULL이다.
        USAGE_FILL = "usage_fill"
        PATTERN_CONNECTION = "pattern_connection"

    # 로그인 전에는 NULL이다. 로그인 티켓에서 채운다.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    # 새 문장은 저장에 성공했을 때 채운다. 저장이 되돌려지면 NULL로 남는다.
    analysis = models.ForeignKey(
        SentenceAnalysis, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    path = models.CharField(max_length=30, choices=Path.choices, null=True)  # noqa: DJ001
    purpose = models.CharField(max_length=30, choices=Purpose.choices, null=True)  # noqa: DJ001
    model = models.CharField(max_length=255, null=True)  # noqa: DJ001
    input_tokens = models.IntegerField(null=True)
    cached_input_tokens = models.IntegerField(null=True)
    output_tokens = models.IntegerField(null=True)
    success = models.BooleanField()
    attempt = models.SmallIntegerField(null=True)
    # 탈퇴한 Google 계정의 그날 행이다(PR #244). 같은 계정이 그날 다시 가입하면 하루 한도에 더한다.
    # Google 계정 식별자를 서버 비밀값으로 HMAC한 값이고, 자정이 지나면 행째 지운다.
    withdrawn_key = models.CharField(max_length=64, null=True)  # noqa: DJ001
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "usage_log"
        constraints = [
            # request에는 처리 경로만, llm에는 호출 목적만 둔다(schema.md).
            models.CheckConstraint(
                condition=models.Q(kind="request", path__isnull=False, purpose__isnull=True)
                | models.Q(kind="llm", path__isnull=True, purpose__isnull=False),
                name="usage_log_kind_fields",
            )
        ]
        # 하루 토큰 사용량을 사용자별로 센다(#28).
        indexes = [
            models.Index(fields=["user", "created_at"], name="usage_log_user_created"),
            models.Index(
                fields=["withdrawn_key", "created_at"],
                condition=models.Q(withdrawn_key__isnull=False),
                name="usage_log_withdrawn_created",
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.path or self.purpose} #{self.pk}"


class Word(models.Model):
    """단어. JMdict 항목 하나가 한 행이다(design-decisions 24절). 사전에 없는 단어는
    jmdict_seq가 NULL이다(LLM 생성, 다음 티켓). 뜻은 WordSense에 둔다.
    """

    # 대표 표기·읽기(표시용). 조회는 forms·readings로 한다.
    dictionary_form = models.CharField(max_length=255)
    reading = models.CharField(max_length=255)
    # 항목의 모든 한자·가나 표기
    forms = ArrayField(models.TextField())
    # 모든 읽기. 히라가나로 통일한다.
    readings = ArrayField(models.TextField())
    is_common = models.BooleanField()
    # re_restr: {읽기: [허용 표기]}. 한자 표기에 쓰지 않는 읽기(re_nokanji)는 빈 목록이다.
    reading_restrictions = models.JSONField(null=True)
    pos = models.CharField(max_length=255)
    # 단어 전체 태그 + 검색용 뜻 태그의 합집합(analysis.jmdict.WORD_TAGS·SENSE_TAGS)
    tags = ArrayField(models.TextField())
    jmdict_seq = models.IntegerField(null=True, unique=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "word"
        indexes = [
            GinIndex(fields=["forms"], name="word_forms_gin"),
            GinIndex(fields=["readings"], name="word_readings_gin"),
            GinIndex(fields=["tags"], name="word_tags_gin"),
        ]
        constraints = [
            # 사전에 없는 단어의 동시 생성 중복 방지(design-decisions 25절)
            models.UniqueConstraint(
                fields=["dictionary_form", "reading"],
                condition=models.Q(jmdict_seq__isnull=True),
                name="word_without_jmdict_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(dictionary_form="") & ~models.Q(reading=""),
                name="word_display_not_empty",
            ),
        ]

    def __str__(self):
        return f"{self.dictionary_form}【{self.reading}】"


class WordSense(models.Model):
    """단어 뜻. id가 고정 뜻 식별자이고 JMdict 뜻 번호는 참고용이다."""

    class Origin(models.TextChoices):
        JMDICT = "jmdict"
        LLM = "llm"

    class MeaningSource(models.TextChoices):
        DICTIONARY = "dictionary"
        LLM = "llm"
        ADMIN = "admin"

    class MeaningStatus(models.TextChoices):
        # 검수 전. 'AI 번역'으로 보인다.
        AI = "ai"
        REVIEWED = "reviewed"
        # 한국어 뜻 생성(word_gloss)에 실패했다. meaning_ko는 NULL이고 다음 새 문장에서 다시 만든다.
        FAILED = "failed"

    word = models.ForeignKey(Word, on_delete=models.CASCADE, related_name="senses")
    jmdict_sense_index = models.SmallIntegerField(null=True)
    # JMdict 영어 뜻 목록(CC BY-SA 4.0)
    gloss_en = models.JSONField(null=True)
    tags = ArrayField(models.TextField())
    pair_form = models.CharField(max_length=255, null=True)  # noqa: DJ001
    # stagk/stagr: {"forms": [...], "readings": [...]} 중 있는 것만
    applies_to = models.JSONField(null=True)
    sense_origin = models.CharField(max_length=10, choices=Origin.choices)
    # 이 뜻 자체의 검수 상태. jmdict는 approved, llm은 pending으로 시작한다.
    sense_status = models.CharField(max_length=20, choices=ReviewStatus.choices)
    meaning_ko = models.TextField(null=True)  # noqa: DJ001
    meaning_source = models.CharField(  # noqa: DJ001
        max_length=30, choices=MeaningSource.choices, null=True
    )
    meaning_status = models.CharField(max_length=20, choices=MeaningStatus.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "word_sense"
        constraints = [
            models.UniqueConstraint(
                fields=["word", "jmdict_sense_index"], name="word_sense_index_unique"
            ),
        ]

    def __str__(self):
        return f"{self.word_id} #{self.jmdict_sense_index}"


class UserSentence(models.Model):
    """사용자가 분석한 문장(분석 기록, #93). 개인 원문은 이 테이블에만 둔다.

    본인 user_id로만 조회하고 Django admin에 등록하지 않는다. 응답에 분석 결과가 나갔고 공용
    분석 행에 저장된 결과가 있을 때만 저장·갱신한다(analysis.user_sentences).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sentences"
    )
    # 정규화 전 원문의 SHA-256. 숫자만 다른 원문도 따로 둔다.
    original_hash = models.CharField(max_length=64)
    original_text = models.TextField()
    # 이름 카드의 위치(원문 UTF-16)와 가나·한글 읽기. 개인 데이터라 공용 분석에 넣지 않는다.
    name_readings = models.JSONField(default=list)
    analysis = models.ForeignKey(
        SentenceAnalysis, on_delete=models.PROTECT, related_name="user_sentences"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_analyzed_at = models.DateTimeField()

    class Meta:
        db_table = "user_sentence"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "original_hash"], name="user_sentence_original_unique"
            ),
        ]

    def __str__(self):
        # 원문을 담지 않는다.
        return f"{self.user_id} #{self.pk}"


class DesignatedName(models.Model):
    """지정한 이름(#136): 사용자가 단어 카드의 표기를 이름으로 지정한 것. 개인 데이터다.

    user_sentence 원문과 같이 본인 user_id로만 조회·수정·삭제하고 Django admin에 등록하지 않는다.
    공용 분석·공용 단어·LLM 요청에는 넣지 않는다.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="designated_names"
    )
    # 원문 토큰의 표층형
    surface = models.CharField(max_length=50)
    # 히라가나 읽기. 없으면 NULL이다.
    reading = models.CharField(max_length=50, null=True)  # noqa: DJ001
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "designated_name"
        constraints = [
            models.UniqueConstraint(fields=["user", "surface"], name="designated_name_unique"),
        ]

    def __str__(self):
        # 표기를 담지 않는다.
        return f"{self.user_id} #{self.pk}"


class EvalSentence(models.Model):
    """평가 문장(FR-A26, #177). 관리자가 직접 쓴 문장, 이용 가능한 자료, 동의를 받은 자료만
    넣는다(NFR-13). 사용자 원문이 아니라 admin에 보여도 된다.
    """

    class Category(models.TextChoices):
        NORMAL = "normal", "정상"
        NO_GRAMMAR = "no_grammar", "문법 없음"
        HOMOGRAPH = "homograph", "동형이의"
        CONTRACTION = "contraction", "축약"
        QUOTATION = "quotation", "인용"
        TECHNICAL = "technical", "기술 문서"
        OUT_OF_SCOPE = "out_of_scope", "범위 밖"

    text = models.TextField("문장")
    category = models.CharField("유형", max_length=30, choices=Category.choices)
    # 끄면 다음 실행부터 빠진다. 지난 실행 결과가 가리키므로 지우지 않고 끈다.
    is_active = models.BooleanField("사용", default=True)
    note = models.TextField("메모", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "eval_sentence"
        verbose_name = verbose_name_plural = "평가 문장"

    def __str__(self):
        return f"#{self.pk} {self.text[:30]}"


class EvalRun(models.Model):
    """평가 세트를 한 번 돌린 것(#177). 지표는 결과·항목에서 계산한다(analysis.evaluation)."""

    class Status(models.TextChoices):
        RUNNING = "running", "진행 중"
        COMPLETE = "complete", "완료"
        FAILED = "failed", "실패"

    status = models.CharField("상태", max_length=30, choices=Status.choices, default=Status.RUNNING)
    model = models.CharField("모델", max_length=255, blank=True)
    note = models.TextField("메모", blank=True)
    created_at = models.DateTimeField("실행 시각", auto_now_add=True)
    finished_at = models.DateTimeField("끝난 시각", null=True, blank=True)

    class Meta:
        db_table = "eval_run"
        verbose_name = verbose_name_plural = "평가 실행"

    def __str__(self):
        return f"평가 실행 #{self.pk}"


class EvalResult(models.Model):
    """평가 실행에서 문장 하나의 결과(#177). text는 실행 때의 평가 문장이다. 문장을 고치면 지난
    채점을 이어받지 않는 기준이 된다.
    """

    run = models.ForeignKey(EvalRun, on_delete=models.CASCADE, related_name="results")
    sentence = models.ForeignKey(EvalSentence, on_delete=models.PROTECT, related_name="results")
    text = models.TextField("문장")
    translation_ko = models.TextField("번역", null=True, blank=True)  # noqa: DJ001
    failed = models.BooleanField("실패", default=False)
    error = models.CharField("오류", max_length=100, blank=True)
    # 관리자가 적는다. 분석이 보이지 않은 문법의 수로, 구간 정확도의 분모에 들어간다. NULL은 아직
    # 적지 않음이다. 지난 실행과 항목까지 같은 결과면 그 값을 이어받는다.
    missed = models.PositiveIntegerField("놓친 문법 수", null=True, blank=True)
    calls = models.PositiveIntegerField("호출 수", default=0)
    input_tokens = models.PositiveIntegerField("입력 토큰", default=0)
    cached_input_tokens = models.PositiveIntegerField("캐시된 입력 토큰", default=0)
    output_tokens = models.PositiveIntegerField("출력 토큰", default=0)
    # 이 문장을 분석한 사용 기록의 request 행. LLM 호출 행은 그 뒤의 같은 분석 행 기록이다.
    usage_request = models.ForeignKey(
        UsageLog, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "eval_result"
        verbose_name = verbose_name_plural = "평가 결과"

    def __str__(self):
        return f"{self.run} · {self.sentence}"


class EvalItem(models.Model):
    """평가 결과의 문법 항목 하나(#177). 사이드 패널에 보이는 항목(구성 문법 포함)이다. 위치는
    평가 문장의 UTF-16 위치다.
    """

    class Grade(models.TextChoices):
        UNGRADED = "ungraded", "미채점"
        CORRECT = "correct", "맞다"
        AMBIGUOUS = "ambiguous", "애매하다"
        WRONG_USAGE = "wrong_usage", "용법이 틀렸다"
        WRONG_SPAN = "wrong_span", "구간이 틀렸다"

    result = models.ForeignKey(EvalResult, on_delete=models.CASCADE, related_name="items")
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    surface = models.CharField("구간", max_length=255)
    state = models.CharField("상태", max_length=30)
    # 미확정이면 패턴 이름, 그 밖에는 용법 이름(화면 제목)
    name = models.CharField("이름", max_length=255)
    pattern_name = models.CharField("패턴", max_length=255)
    # 채점 이어받기 기준. 용법이 합쳐져 지워져도 남도록 참조가 아닌 값으로 둔다.
    pattern_ref = models.BigIntegerField()
    usage_ref = models.BigIntegerField(null=True)
    # 해석 갈림의 대안 용법 이름
    alternatives = models.JSONField("대안", default=list)
    review_status = models.CharField("검수 상태", max_length=30)
    grade = models.CharField("채점", max_length=30, choices=Grade.choices, default=Grade.UNGRADED)

    class Meta:
        db_table = "eval_item"
        verbose_name = verbose_name_plural = "평가 항목"

    def __str__(self):
        return f"{self.surface} {self.name}"
