"""사용자 관리. is_staff는 관리자가 여기서 준다. google_sub는 로그인이 정하므로 읽기만 한다."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    fieldsets = (*UserAdmin.fieldsets, ("Google", {"fields": ("google_sub",)}))
    readonly_fields = ("google_sub",)
    list_display = ("username", "email", "google_sub", "is_staff", "is_active")
    search_fields = ("username", "email", "google_sub")
