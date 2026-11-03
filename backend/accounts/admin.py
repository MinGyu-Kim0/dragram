"""사용자 관리. is_staff는 관리자가 여기서 준다. google_sub는 로그인이 정하므로 읽기만 한다."""

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from accounts import withdrawal
from accounts.models import ExtensionToken, User
from analysis import limits
from analysis.models import UsageLog
from analysis.usage import today_start


@admin.register(User)
class AccountAdmin(UserAdmin):
    fieldsets = (
        *UserAdmin.fieldsets,
        ("Google", {"fields": ("google_sub",)}),
        ("사용량", {"fields": ("today_usage", "usage_reset_at")}),
    )
    readonly_fields = ("google_sub", "today_usage", "usage_reset_at")
    list_display = ("username", "email", "google_sub", "is_staff", "is_active", "today_tokens")
    search_fields = ("username", "email", "google_sub")
    actions = ["reset_usage"]

    def get_queryset(self, request):
        # 하루 한도(limits.today_tokens)와 같이 오늘(초기화했으면 그 뒤) llm 행의 입력+출력 합.
        # 오늘 탈퇴한 같은 Google 계정의 행은 비교값을 SQL로 맞출 수 없어 목록에서만 빠진다.
        start = Value(today_start())
        tokens = Coalesce("input_tokens", 0) + Coalesce("output_tokens", 0)
        today = (
            UsageLog.objects.filter(
                user=OuterRef("pk"),
                kind=UsageLog.Kind.LLM,
                created_at__gte=Greatest(start, Coalesce(OuterRef("usage_reset_at"), start)),
            )
            .values("user")
            .annotate(total=Sum(tokens))
            .values("total")
        )
        return super().get_queryset(request).annotate(_today_tokens=Coalesce(Subquery(today), 0))

    @admin.display(description="오늘 토큰", ordering="_today_tokens")
    def today_tokens(self, user):
        return user._today_tokens

    @admin.display(description="오늘 토큰 / 하루 한도")
    def today_usage(self, user):
        logs = reverse("admin:analysis_usagelog_changelist")
        limit = "없음(관리자)" if user.is_staff else settings.ANALYSIS_DAILY_TOKEN_LIMIT
        return format_html(
            '{} / {} · <a href="{}?user__id__exact={}">사용 기록</a>',
            limits.today_tokens(user),
            limit,
            logs,
            user.pk,
        )

    @admin.action(description="하루 토큰 한도 초기화", permissions=["change"])
    def reset_usage(self, request, queryset):
        # 사용 기록은 그대로 두고, 한도가 이 시각 뒤의 사용만 세게 한다.
        now = timezone.now()
        for user in queryset:
            user.usage_reset_at = now
            user.save(update_fields=["usage_reset_at"])
            self.log_change(request, user, "하루 토큰 한도 초기화")
        self.message_user(
            request, f"{len(queryset)}명의 하루 토큰 한도를 초기화했어요.", messages.SUCCESS
        )

    # 이메일로 받은 탈퇴 요청(정지된 계정 등)도 화면 탈퇴와 같이 사용량 기록을 처리한다(#249).
    def delete_model(self, request, obj):
        withdrawal.withdraw(obj)

    def delete_queryset(self, request, queryset):
        for user in queryset:
            withdrawal.withdraw(user)


@admin.register(ExtensionToken)
class ExtensionTokenAdmin(admin.ModelAdmin):
    """확장 버전별로 옛 확장이 아직 쓰이는지 본다(#349). 보기만 한다. 토큰 해시는 보이지 않는다."""

    list_display = ("pk", "user", "extension_version", "last_used_at", "created_at", "revoked_at")
    list_filter = ("extension_version",)
    fields = list_display[1:]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # 지우면 그 사용자의 확장 연결이 끊긴다. 연결은 확장·웹 로그아웃과 탈퇴로만 끊는다. 삭제 권한은
    # 두어야 관리자 화면의 사용자 삭제(탈퇴)가 딸린 토큰을 함께 지울 수 있어, 이 화면만 막는다.
    def delete_view(self, request, object_id, extra_context=None):
        raise PermissionDenied

    def get_actions(self, request):
        return {}
