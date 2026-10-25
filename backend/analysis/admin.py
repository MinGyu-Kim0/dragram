"""패턴·용법 검수 화면(#38).

원문이나 원문 위치를 담은 테이블(sentence_analysis, span_match)은 등록하지 않는다. 패턴·용법은
LLM이 만들므로 여기서 더하거나 지우지 않는다(회화체를 연결하며 자기 용법을 원형 용법으로 합칠
때만 그 용법을 지운다, #64). 단어·뜻도 문장 분석이 뜻 ID를 가리켜 더하거나 지우지 않고, 한국어
뜻만 고친다(#97). 사전에 없는 단어(LLM 생성)는 표기·읽기도 고치고, LLM 뜻은 뜻 화면 액션으로
승인·반려한다(#134). 판별 규칙은 관리자가 여기서 만든다(#55). 상태는 필드가 아니라
액션으로만 바꾸고, 액션은 analysis.review의 상태 전이를 부른다.
"""

import json

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.db.models import Q
from django.forms.models import BaseInlineFormSet
from django.template.response import TemplateResponse
from django.utils import timezone

from analysis import answers, patterns, review, words
from analysis.jmdict import to_hiragana
from analysis.models import (
    FunctionTag,
    GrammarPattern,
    GrammarUsage,
    PatternMorpheme,
    ReviewStatus,
    UsageRule,
    Word,
    WordSense,
)
from analysis.normalize import has_only_known_placeholders
from analysis.rules import condition_problem


def _example_problem(text):
    """관리자가 쓴 예문의 모양 문제. 없으면 None."""
    if not isinstance(text, str) or not text.strip():
        return "예문은 비어 있지 않은 문자열이어야 합니다"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "예문에 저장할 수 없는 문자(짝 없는 서로게이트 등)가 있습니다"
    if len(text) > patterns.EXAMPLE_MAX_LENGTH:
        return f"예문은 {patterns.EXAMPLE_MAX_LENGTH}자 이하여야 합니다"
    if not has_only_known_placeholders(text, ()):
        return "예문에 숫자 자리표시자(⟨N1⟩ 등)를 쓸 수 없습니다"
    return None


class _TestCasesField(forms.JSONField):
    """오류 화면에서 입력을 되보일 때, UTF-8로 쓸 수 없는 문자는 \\u 이스케이프로 보인다."""

    def prepare_value(self, value):
        text = super().prepare_value(value)
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            return json.dumps(value)
        return text


class GrammarPatternForm(forms.ModelForm):
    test_cases = _TestCasesField()

    class Meta:
        model = GrammarPattern
        fields = ["name", "test_cases", "show_parts"]

    def clean_test_cases(self):
        cases = self.cleaned_data["test_cases"]
        if not isinstance(cases, list):
            raise forms.ValidationError("[{text, should_match}] 목록이어야 합니다")
        for case in cases:
            if not isinstance(case, dict) or set(case) != {"text", "should_match"}:
                raise forms.ValidationError("항목마다 text와 should_match만 둡니다")
            if not isinstance(case["should_match"], bool):
                raise forms.ValidationError("should_match는 true 또는 false여야 합니다")
            problem = _example_problem(case["text"])
            if problem:
                raise forms.ValidationError(problem)
        # admin 변경 화면은 한 트랜잭션이라, 여기서 잠근 패턴을 저장(save_model)까지 붙든다.
        refusal = review.test_cases_refusal(self.instance, cases)
        if refusal:
            raise forms.ValidationError(refusal)
        return cases


USAGE_MOVED = "그사이 용법이 원형 용법으로 합쳐지거나 원형 아래로 옮겨졌습니다(다시 엽니다)"


class GrammarUsageForm(forms.ModelForm):
    # 예문 검사를 통과하지 못해 예문 없이 등록된 용법도 있다(NULL).
    example_ja = forms.CharField(widget=forms.Textarea, required=False)
    # 기능 태그는 허용 목록 안에서만 고른다(#151).
    function_tags = forms.MultipleChoiceField(
        choices=FunctionTag.choices, widget=forms.CheckboxSelectMultiple, required=False
    )

    class Meta:
        model = GrammarUsage
        fields = ["explanation_ko", "example_ja", "korean_equivalent", "function_tags"]

    # 용법 화면과 패턴 화면 인라인이 쓰는 칸. 고칠 수 있는 칸과, 대응 표현을 고치면 함께 바뀌는
    # 채움 여부·검수 상태(#152)만 쓴다.
    SAVED_FIELDS = [
        *Meta.fields,
        "korean_equivalent_filled",
        "korean_equivalent_status",
        "function_tags_filled",
        "function_tags_status",
        "updated_at",
    ]

    def clean_korean_equivalent(self):
        # 비우면 '대응 없음'(NULL)이다(#152).
        return (self.cleaned_data["korean_equivalent"] or "").strip() or None

    def clean_function_tags(self):
        # 허용 목록 순서로 둔다(LLM 답과 같은 모양).
        return answers.function_tags(self.cleaned_data["function_tags"])

    def clean_example_ja(self):
        example = self.cleaned_data["example_ja"] or None
        if example is None:
            return None
        problem = _example_problem(example)
        if problem:
            raise forms.ValidationError(problem)
        if not review.matches(patterns.conditions_of(self.instance.pattern), example):
            raise forms.ValidationError("예문이 이 용법의 패턴에 걸리지 않습니다")
        return example

    def clean(self):
        # admin 변경 화면은 한 트랜잭션이라, 여기서 잠근 용법을 저장(save_model)까지 붙든다. 예문은
        # 화면이 읽어 둔 패턴의 조건으로 검사했으므로, 그사이 용법이 원형 용법으로 합쳐지거나
        # 원형 아래로 옮겨졌으면 저장하지 않는다(#64).
        current = (
            GrammarUsage.objects.select_for_update(no_key=True)
            .filter(pk=self.instance.pk)
            .values_list("pattern_id", flat=True)
            .first()
        )
        if current != self.instance.pattern_id:
            raise forms.ValidationError(USAGE_MOVED)
        # 관리자가 고친 대응 표현(비운 것 포함)은 채우기 명령이 다시 채우지 않는다(#152).
        # 관리자가 쓴 값은 검수한 것이다.
        if "korean_equivalent" in self.changed_data:
            self.instance.korean_equivalent_filled = True
            self.instance.korean_equivalent_status = (
                ReviewStatus.APPROVED if self.cleaned_data.get("korean_equivalent") else None
            )
        # 기능 태그도 같다(#151).
        if "function_tags" in self.changed_data:
            self.instance.function_tags_filled = True
            self.instance.function_tags_status = (
                ReviewStatus.APPROVED if self.cleaned_data.get("function_tags") else None
            )
        return super().clean()


class GrammarUsageFormSet(BaseInlineFormSet):
    def get_queryset(self):
        # 화면을 연 뒤 합쳐지거나 옮겨진 용법이 있으면 용법을 하나도 읽지 않는다. admin은 보낸 행과
        # 이 목록을 순서대로 짝지어 다시 그리므로, 행이 다른 용법과 짝지어 보이지 않게 한다.
        if not hasattr(self, "_usages"):
            usages = super().get_queryset()
            if self.is_bound:
                sent = {
                    self.data.get(f"{self.add_prefix(i)}-id")
                    for i in range(self.initial_form_count())
                }
                if not sent <= {str(pk) for pk in usages.values_list("pk", flat=True)}:
                    usages = usages.none()
            self._usages = usages
        return self._usages

    def clean(self):
        # 그러면 보낸 행이 새 행으로 읽힌다. 그 행은 화면에 다시 그려지지 않으므로 용법 화면과 같은
        # 이유를 formset 오류로 보인다.
        if any(form.instance.pk is None for form in self.initial_forms):
            raise forms.ValidationError(USAGE_MOVED)
        super().clean()


class GrammarUsageInline(admin.TabularInline):
    # 용법 화면과 같은 폼이라 같은 예문 검사·합침 확인을 쓴다. 상태는 용법 화면 액션으로 바꾼다.
    model = GrammarUsage
    form = GrammarUsageForm
    formset = GrammarUsageFormSet
    fields = [
        "name",
        "status",
        "origin",
        "explanation_ko",
        "example_ja",
        "korean_equivalent",
        "function_tags",
    ]
    readonly_fields = ["name", "status", "origin"]
    ordering = ["id"]
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class PatternMorphemeInline(admin.TabularInline):
    model = PatternMorpheme
    fields = readonly_fields = ["seq", "lemma", "pos1", "pos2", "conjugation_form"]
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


def _apply(model_admin, request, queryset, transition):
    """선택한 행마다 상태 전이를 부른다. 거부되면 그 행은 바꾸지 않고 이유를 보인다."""
    done = 0
    for obj in queryset:
        try:
            transition(obj)
        except review.Refused as refused:
            model_admin.message_user(request, f"{obj}: {refused}", messages.ERROR)
        else:
            done += 1
    if done:
        model_admin.message_user(request, f"{done}개를 처리했습니다", messages.SUCCESS)


def _review_action(name, transition, description):
    """선택한 행마다 상태 전이를 부르는 admin 액션."""

    def action(model_admin, request, queryset):
        _apply(model_admin, request, queryset, transition)

    action.__name__ = name
    return admin.action(description=description)(action)


class _ReviewedAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        # 기본 '선택한 항목 삭제'는 쓰지 않는다.
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


class GrammarPatternActionForm(ActionForm):
    # '원형에 연결' 액션이 쓰는 원형 패턴 ID(#63)
    base_pattern_id = forms.CharField(required=False, label="원형 패턴 ID")


def _usage_mapping(data):
    """중간 화면에서 고른 대응표 {자기 용법 ID: 합칠 원형 용법 ID, 옮기면 None}. 고르지 않은
    용법이 있거나 값이 잘못됐으면 None이다.
    """
    mapping = {}
    for key, value in data.items():
        if not key.startswith("usage_"):
            continue
        source = key.removeprefix("usage_")
        if not source.isdecimal() or not (value == "move" or value.isdecimal()):
            return None
        mapping[int(source)] = None if value == "move" else int(value)
    return mapping


@admin.action(description="원형에 연결(원형 패턴 ID를 넣고)")
def link_variant(model_admin, request, queryset):
    """선택한 회화체 패턴을 원형 패턴 ID 칸의 패턴에 연결한다(#63).

    패턴 하나를 골랐고 반려되지 않은 자기 용법이 남았으면, 먼저 용법마다 합칠 원형 용법이나
    옮김을 고르는 화면을 보인다. 이름으로 자동 대응하지 않는다(#64).
    """
    raw = request.POST.get("base_pattern_id", "").strip()
    base = GrammarPattern.objects.filter(pk=int(raw)).first() if raw.isdecimal() else None
    if base is None:
        model_admin.message_user(
            request, "원형 패턴 ID 칸에 있는 패턴의 ID를 넣어야 합니다", messages.ERROR
        )
        return None
    # 용법을 옮기거나 합쳐 지우므로 용법 권한도 있어야 한다(패턴 권한만으로는 안 된다).
    may_merge = request.user.has_perms(
        ["analysis.change_grammarusage", "analysis.delete_grammarusage"]
    )
    if "apply" in request.POST:
        if not may_merge:
            model_admin.message_user(
                request, "용법을 합치거나 옮길 권한(용법 변경·삭제)이 없습니다", messages.ERROR
            )
            return None
        mapping = _usage_mapping(request.POST)
        if mapping is None:
            model_admin.message_user(
                request, "용법마다 합칠 원형 용법이나 옮김을 골라야 합니다", messages.ERROR
            )
            return None
        _apply(model_admin, request, queryset, lambda obj: review.link_variant(obj, base, mapping))
        return None
    chosen = list(queryset)
    usages = (
        GrammarUsage.objects.filter(pattern=chosen[0]).exclude(status=ReviewStatus.REJECTED)
        if len(chosen) == 1
        else GrammarUsage.objects.none()
    )
    if not usages or not may_merge:
        # 여러 개를 골랐거나 용법 권한이 없으면 자기 용법이 남은 패턴은 거부 이유를 보인다.
        _apply(model_admin, request, chosen, lambda obj: review.link_variant(obj, base))
        return None
    return TemplateResponse(
        request,
        "admin/analysis/grammarpattern/link_variant.html",
        {
            **model_admin.admin_site.each_context(request),
            "title": "원형에 연결",
            "opts": model_admin.model._meta,
            "pattern": chosen[0],
            "base": base,
            "usages": usages.order_by("id"),
            "targets": base.usages.exclude(status=ReviewStatus.REJECTED).order_by("id"),
        },
    )


@admin.register(GrammarPattern)
class GrammarPatternAdmin(_ReviewedAdmin):
    form = GrammarPatternForm
    action_form = GrammarPatternActionForm
    list_display = [
        "id",
        "name",
        "status",
        "is_active",
        "usage_closed",
        "register",
        "variant_of",
        "created_at",
    ]
    list_filter = ["status", "is_active", "usage_closed", "register"]
    # 용법 이름으로 찾아도 admin이 중복 행을 걸러 패턴은 한 번 나온다.
    search_fields = ["name", "usages__name"]
    fields = [
        "name",
        "test_cases",
        "show_parts",
        "status",
        "is_active",
        "usage_closed",
        "register",
        "variant_of",
        "morpheme_key",
    ]
    readonly_fields = [
        "status",
        "is_active",
        "usage_closed",
        "register",
        "variant_of",
        "morpheme_key",
    ]
    inlines = [PatternMorphemeInline, GrammarUsageInline]

    def save_model(self, request, obj, form, change):
        # show_parts는 조회할 때만 읽는 표시 칸이라 그대로 쓴다(#65). test_cases는 활성 상태·
        # 패턴 세트 버전과 함께 바꾼다.
        GrammarPattern.objects.filter(pk=obj.pk).update(name=obj.name, show_parts=obj.show_parts)
        review.update_test_cases(obj, form.cleaned_data["test_cases"])

    def save_formset(self, request, form, formset, change):
        if formset.model is not GrammarUsage:
            return super().save_formset(request, form, formset, change)
        # 용법은 고칠 수 있는 칸만 쓴다(GrammarUsageAdmin.save_model과 같다). commit=False도 admin
        # 변경 기록에 쓰는 changed_objects 등을 채운다.
        for usage in formset.save(commit=False):
            usage.save(update_fields=GrammarUsageForm.SAVED_FIELDS)

    actions = [
        _review_action("approve", review.approve_pattern, "승인"),
        _review_action("reject", review.reject_pattern, "반려"),
        _review_action("unreject", review.unreject_pattern, "반려 취소(미검수로)"),
        _review_action("unapprove", review.unapprove_pattern, "승인 취소(미검수로)"),
        _review_action("close_usages", review.close_usages, "용법 완결 표시"),
        _review_action("open_usages", review.open_usages, "용법 완결 해제"),
        link_variant,
        _review_action("unlink_variant", review.unlink_variant, "원형 연결 해제"),
    ]


class ExampleFilter(admin.SimpleListFilter):
    """예문 검사를 통과하지 못해 예문 없이(NULL) 등록된 용법."""

    title = "예문"
    parameter_name = "example"

    def lookups(self, request, model_admin):
        return [("no", "예문 없음"), ("yes", "예문 있음")]

    def queryset(self, request, queryset):
        if self.value() not in ("no", "yes"):
            return queryset
        return queryset.filter(example_ja__isnull=self.value() == "no")


@admin.register(GrammarUsage)
class GrammarUsageAdmin(_ReviewedAdmin):
    form = GrammarUsageForm
    list_display = ["id", "name", "pattern", "status", "origin", "updated_at"]
    list_filter = ["status", "origin", ExampleFilter]
    search_fields = ["name", "pattern__name"]
    fields = [
        "name",
        "pattern",
        "status",
        "origin",
        "explanation_ko",
        "example_ja",
        "korean_equivalent",
        "function_tags",
    ]
    readonly_fields = ["name", "pattern", "status", "origin"]

    def save_model(self, request, obj, form, change):
        # 고칠 수 있는 칸만 쓴다. 폼을 연 뒤 액션이 바꾼 상태를 화면이 읽어 둔 값으로 덮지 않는다.
        obj.save(update_fields=GrammarUsageForm.SAVED_FIELDS)

    actions = [
        _review_action("approve", review.approve_usage, "승인"),
        _review_action("reject", review.reject_usage, "반려"),
        _review_action("unreject", review.unreject_usage, "반려 취소(미검수로)"),
        _review_action("unapprove", review.unapprove_usage, "승인 취소(미검수로)"),
        _review_action(
            "approve_korean_equivalent", review.approve_korean_equivalent, "대응 표현 승인"
        ),
        _review_action("approve_function_tags", review.approve_function_tags, "기능 태그 승인"),
    ]


class UsageRuleForm(forms.ModelForm):
    condition = _TestCasesField()
    test_cases = _TestCasesField()

    class Meta:
        model = UsageRule
        fields = ["pattern", "usage", "condition", "test_cases"]

    def clean_condition(self):
        condition = self.cleaned_data["condition"]
        problem = condition_problem(condition)
        if problem:
            raise forms.ValidationError(problem)
        return condition

    def clean_test_cases(self):
        cases = self.cleaned_data["test_cases"]
        if not isinstance(cases, list):
            raise forms.ValidationError("[{text, should_apply}] 목록이어야 합니다")
        for case in cases:
            if not isinstance(case, dict) or set(case) != {"text", "should_apply"}:
                raise forms.ValidationError("항목마다 text와 should_apply만 둡니다")
            if not isinstance(case["should_apply"], bool):
                raise forms.ValidationError("should_apply는 true 또는 false여야 합니다")
            problem = _example_problem(case["text"])
            if problem:
                raise forms.ValidationError(problem)
        return cases

    def clean(self):
        cleaned = super().clean()
        pattern, usage = cleaned.get("pattern"), cleaned.get("usage")
        if pattern and usage:
            # 용법은 그 패턴 소속이다. 연결된 회화체 패턴이면 원형의 용법이다(#63). 원형 연결·
            # 용법 병합(#64)과 직렬화하도록 연결 잠금을 공유로 잡은 뒤 DB에서 다시 읽는다. admin
            # 변경 화면은 한 트랜잭션이라 저장(save_model)까지 잠금이 이어진다.
            patterns.lock_links()
            base_id = GrammarPattern.objects.values_list("variant_of_id", flat=True).get(
                pk=pattern.pk
            )
            if not GrammarUsage.objects.filter(
                pk=usage.pk, pattern_id=base_id or pattern.pk
            ).exists():
                self.add_error("usage", "고른 패턴의 용법이어야 합니다")
        return cleaned


@admin.register(UsageRule)
class UsageRuleAdmin(admin.ModelAdmin):
    form = UsageRuleForm
    list_display = ["id", "pattern", "usage", "status", "approved_at", "updated_at"]
    list_filter = ["status"]
    search_fields = ["pattern__name", "usage__name"]
    fields = ["pattern", "usage", "condition", "test_cases", "status", "created_by"]
    actions = ["approve", _review_action("retire", review.retire_rule, "폐기")]

    @admin.action(description="승인")
    def approve(self, request, queryset):
        # 승인한 관리자를 남긴다.
        _apply(self, request, queryset, lambda rule: review.approve_rule(rule, request.user))

    def get_readonly_fields(self, request, obj=None):
        # 미검수 규칙만 고친다. 승인된 규칙을 바꾸려면 폐기하고 새로 만든다.
        if obj is not None and obj.status != UsageRule.Status.PENDING:
            return self.fields
        return ["status", "created_by"]

    def has_delete_permission(self, request, obj=None):
        # 판정 기록(span_match.rule)이 가리키므로 지우지 않는다.
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.save()
            return
        # 폼을 연 뒤 액션이 승인·폐기했으면 덮지 않고 알린다.
        saved = UsageRule.objects.filter(pk=obj.pk, status=UsageRule.Status.PENDING).update(
            pattern=obj.pattern,
            usage=obj.usage,
            condition=obj.condition,
            test_cases=obj.test_cases,
            updated_at=timezone.now(),
        )
        if not saved:
            self.message_user(request, "그사이 승인·폐기돼 저장하지 않았습니다", messages.ERROR)


class WordSenseForm(forms.ModelForm):
    class Meta:
        model = WordSense
        fields = ["meaning_ko"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 아직 한국어 뜻이 없는 다른 뜻 때문에 저장이 막히지 않게 한다. 비우기는 아래에서 막는다.
        self.fields["meaning_ko"].required = False

    def clean_meaning_ko(self):
        meaning = self.cleaned_data["meaning_ko"]
        if "meaning_ko" in self.changed_data and not meaning:
            raise forms.ValidationError("한국어 뜻을 비울 수 없습니다")
        return meaning


class WordSenseInline(admin.TabularInline):
    # LLM 뜻의 승인·반려는 뜻 화면 액션으로 한다(#134).
    model = WordSense
    form = WordSenseForm
    show_change_link = True
    fields = [
        "jmdict_sense_index",
        "gloss_en",
        "tags",
        "sense_origin",
        "sense_status",
        "meaning_ko",
        "meaning_source",
        "meaning_status",
    ]
    readonly_fields = [field for field in fields if field != "meaning_ko"]
    ordering = ["jmdict_sense_index", "id"]
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class MeaningFilter(admin.SimpleListFilter):
    """단어의 뜻 가운데 하나라도 그 상태인 단어."""

    title = "한국어 뜻"
    parameter_name = "meaning"
    _choices = {
        "not_in_dictionary": ("사전에 없는 단어", Q(jmdict_seq__isnull=True)),
        "missing": (
            "한국어 뜻 없음",
            Q(senses__meaning_ko__isnull=True)
            & ~Q(senses__meaning_status=WordSense.MeaningStatus.FAILED),
        ),
        "ai": (
            "AI 번역",
            Q(
                senses__meaning_ko__isnull=False,
                senses__meaning_status=WordSense.MeaningStatus.AI,
            ),
        ),
        "reviewed": ("검수됨", Q(senses__meaning_status=WordSense.MeaningStatus.REVIEWED)),
        "failed": ("생성 실패", Q(senses__meaning_status=WordSense.MeaningStatus.FAILED)),
    }

    def lookups(self, request, model_admin):
        return [(value, label) for value, (label, _) in self._choices.items()]

    def queryset(self, request, queryset):
        if self.value() not in self._choices:
            return queryset
        return queryset.filter(self._choices[self.value()][1]).distinct()


def _meaning_action(name, old, new, description):
    """선택한 단어의 뜻 가운데 한국어 뜻이 있고 상태가 old인 뜻을 new로 바꾸는 admin 액션."""

    def action(model_admin, request, queryset):
        done = WordSense.objects.filter(
            word__in=queryset, meaning_ko__isnull=False, meaning_status=old
        ).update(meaning_status=new)
        model_admin.message_user(request, f"뜻 {done}개를 처리했습니다", messages.SUCCESS)

    action.__name__ = name
    return admin.action(description=description)(action)


class WordForm(forms.ModelForm):
    """사전에 없는 단어(LLM 생성)의 표기·읽기. 사전 단어는 읽기 전용이라 이 칸이 폼에 없다."""

    class Meta:
        model = Word
        fields = ["dictionary_form", "reading"]

    def clean_reading(self):
        reading = self.cleaned_data["reading"].strip()
        if not words.is_kana(reading):
            raise forms.ValidationError("읽기는 가나로 씁니다")
        return to_hiragana(reading)

    def clean(self):
        cleaned = super().clean()
        form, reading = cleaned.get("dictionary_form"), cleaned.get("reading")
        if form and reading:
            taken = Word.objects.filter(
                jmdict_seq__isnull=True, dictionary_form=form, reading=reading
            ).exclude(pk=self.instance.pk)
            if taken.exists():
                raise forms.ValidationError("같은 표기·읽기의 사전에 없는 단어가 이미 있습니다")
        return cleaned


@admin.register(Word)
class WordAdmin(_ReviewedAdmin):
    form = WordForm
    list_display = ["id", "dictionary_form", "reading", "in_dictionary", "updated_at"]
    list_filter = [MeaningFilter]
    # 검색은 get_search_results가 표기·읽기 목록으로 한다. 검색창을 보이려고 칸을 둔다.
    search_fields = ["dictionary_form"]
    fields = readonly_fields = [
        "dictionary_form",
        "reading",
        "forms",
        "readings",
        "pos",
        "tags",
        "is_common",
        "reading_restrictions",
        "jmdict_seq",
    ]
    inlines = [WordSenseInline]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.jmdict_seq is None:
            return [f for f in self.readonly_fields if f not in ("dictionary_form", "reading")]
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        # 사전에 없는 단어의 표기·읽기만 쓴다. 찾기는 forms·readings로 하므로 함께 바꾼다.
        if obj.jmdict_seq is None and form.changed_data:
            Word.objects.filter(pk=obj.pk).update(
                dictionary_form=obj.dictionary_form,
                reading=obj.reading,
                forms=list(dict.fromkeys([obj.dictionary_form, obj.reading])),
                readings=[obj.reading],
                updated_at=timezone.now(),
            )

    @admin.display(boolean=True, description="사전에 있음")
    def in_dictionary(self, word):
        return word.jmdict_seq is not None

    def get_search_results(self, request, queryset, search_term):
        term = search_term.strip()
        if not term:
            return queryset, False
        found = Q(forms__contains=[term]) | Q(readings__contains=[to_hiragana(term)])
        return queryset.filter(found), False

    def save_formset(self, request, form, formset, change):
        # 고친 한국어 뜻만 쓰고 관리자 검수로 둔다. 화면이 읽어 둔 다른 칸으로 덮지 않는다.
        # commit=False도 admin 변경 기록에 쓰는 changed_objects 등을 채운다.
        for sense in formset.save(commit=False):
            sense.meaning_source = WordSense.MeaningSource.ADMIN
            sense.meaning_status = WordSense.MeaningStatus.REVIEWED
            sense.save(
                update_fields=["meaning_ko", "meaning_source", "meaning_status", "updated_at"]
            )

    actions = [
        _meaning_action(
            "mark_reviewed",
            WordSense.MeaningStatus.AI,
            WordSense.MeaningStatus.REVIEWED,
            "검수 완료",
        ),
        _meaning_action(
            "unmark_reviewed",
            WordSense.MeaningStatus.REVIEWED,
            WordSense.MeaningStatus.AI,
            "검수 취소(AI 번역으로)",
        ),
    ]


def _sense_action(name, old, new, description):
    """선택한 뜻 가운데 LLM이 만들고 상태가 old인 뜻을 new로 바꾸는 admin 액션(#134).
    JMdict 뜻은 바꾸지 않는다.
    """

    def action(model_admin, request, queryset):
        done = queryset.filter(sense_origin=WordSense.Origin.LLM, sense_status__in=old).update(
            sense_status=new, updated_at=timezone.now()
        )
        model_admin.message_user(request, f"뜻 {done}개를 처리했습니다", messages.SUCCESS)

    action.__name__ = name
    return admin.action(description=description)(action)


@admin.register(WordSense)
class WordSenseAdmin(_ReviewedAdmin):
    """뜻 하나씩 승인·반려한다. 반려된 뜻은 후보·응답에서 빠진다(#134)."""

    list_display = ["id", "word", "meaning_ko", "sense_origin", "sense_status", "meaning_status"]
    list_filter = ["sense_origin", "sense_status"]
    search_fields = ["word__dictionary_form", "meaning_ko"]
    fields = readonly_fields = [
        "word",
        "jmdict_sense_index",
        "gloss_en",
        "tags",
        "sense_origin",
        "sense_status",
        "meaning_ko",
        "meaning_source",
        "meaning_status",
    ]
    actions = [
        _sense_action(
            "approve_senses", [ReviewStatus.PENDING], ReviewStatus.APPROVED, "LLM 뜻 승인"
        ),
        _sense_action(
            "reject_senses",
            [ReviewStatus.PENDING, ReviewStatus.APPROVED],
            ReviewStatus.REJECTED,
            "LLM 뜻 반려",
        ),
        _sense_action(
            "unreject_senses", [ReviewStatus.REJECTED], ReviewStatus.PENDING, "반려 취소(미검수로)"
        ),
    ]
