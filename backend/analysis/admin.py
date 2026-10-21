"""패턴·용법 검수 화면(#38).

원문이나 원문 위치를 담은 테이블(sentence_analysis, span_match)은 등록하지 않는다. 패턴·용법은
LLM이 만들므로 여기서 더하거나 지우지 않는다. 상태는 필드가 아니라 액션으로만 바꾸고, 액션은
analysis.review의 상태 전이를 부른다.
"""

from django import forms
from django.contrib import admin, messages

from analysis import patterns, review
from analysis.models import GrammarPattern, GrammarUsage, PatternMorpheme
from analysis.normalize import has_only_known_placeholders


def _example_problem(text):
    """관리자가 쓴 예문의 모양 문제. 없으면 None."""
    if not isinstance(text, str) or not text.strip():
        return "예문은 비어 있지 않은 문자열이어야 합니다"
    if len(text) > patterns.EXAMPLE_MAX_LENGTH:
        return f"예문은 {patterns.EXAMPLE_MAX_LENGTH}자 이하여야 합니다"
    if not has_only_known_placeholders(text, ()):
        return "예문에 숫자 자리표시자(⟨N1⟩ 등)를 쓸 수 없습니다"
    return None


class GrammarPatternForm(forms.ModelForm):
    class Meta:
        model = GrammarPattern
        fields = ["name", "test_cases"]

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
        return cases


class PatternMorphemeInline(admin.TabularInline):
    model = PatternMorpheme
    fields = readonly_fields = ["seq", "lemma", "pos1", "pos2", "conjugation_form"]
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


def _review_action(transition, description):
    """선택한 행마다 상태 전이를 부르는 admin 액션. 거부되면 그 행은 바꾸지 않고 이유를 보인다."""

    def action(model_admin, request, queryset):
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

    action.__name__ = transition.__name__.split("_")[0]
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


@admin.register(GrammarPattern)
class GrammarPatternAdmin(_ReviewedAdmin):
    form = GrammarPatternForm
    list_display = ["id", "name", "status", "is_active", "usage_closed", "created_at"]
    list_filter = ["status", "is_active", "usage_closed"]
    search_fields = ["name"]
    fields = ["name", "test_cases", "status", "is_active", "usage_closed", "morpheme_key"]
    readonly_fields = ["status", "is_active", "usage_closed", "morpheme_key"]
    inlines = [PatternMorphemeInline]
    actions = [
        _review_action(review.approve_pattern, "승인"),
        _review_action(review.reject_pattern, "반려"),
        _review_action(review.unreject_pattern, "반려 취소(미검수로)"),
        _review_action(review.unapprove_pattern, "승인 취소(미검수로)"),
        _review_action(review.close_usages, "용법 완결 표시"),
        _review_action(review.open_usages, "용법 완결 해제"),
    ]


class GrammarUsageForm(forms.ModelForm):
    class Meta:
        model = GrammarUsage
        fields = ["explanation_ko", "example_ja"]

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


@admin.register(GrammarUsage)
class GrammarUsageAdmin(_ReviewedAdmin):
    form = GrammarUsageForm
    list_display = ["id", "name", "pattern", "status", "origin", "updated_at"]
    list_filter = ["status", "origin"]
    search_fields = ["name", "pattern__name"]
    fields = ["name", "pattern", "status", "origin", "explanation_ko", "example_ja"]
    readonly_fields = ["name", "pattern", "status", "origin"]
    actions = [
        _review_action(review.approve_usage, "승인"),
        _review_action(review.reject_usage, "반려"),
        _review_action(review.unreject_usage, "반려 취소(미검수로)"),
        _review_action(review.unapprove_usage, "승인 취소(미검수로)"),
    ]
