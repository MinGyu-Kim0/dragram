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
    분석 행에 저장된 결과가 있을 때만 저장·갱신한다(analysis.history).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sentences"
    )
    # 정규화 전 원문의 SHA-256. 숫자만 다른 원문도 따로 둔다.
    original_hash = models.CharField(max_length=64)
    original_text = models.TextField()
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
