"""사용자 관리. is_staff는 관리자가 여기서 준다. google_sub는 로그인이 정하므로 읽기만 한다."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied

from accounts import withdrawal
from accounts.models import ExtensionToken, User


@admin.register(User)
class AccountAdmin(UserAdmin):
    fieldsets = (*UserAdmin.fieldsets, ("Google", {"fields": ("google_sub",)}))
    readonly_fields = ("google_sub",)
    list_display = ("username", "email", "google_sub", "is_staff", "is_active")
    search_fields = ("username", "email", "google_sub")

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
