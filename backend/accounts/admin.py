"""사용자 관리. is_staff는 관리자가 여기서 준다. google_sub는 로그인이 정하므로 읽기만 한다."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts import withdrawal
from accounts.models import User


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
