from django.urls import path

from accounts import views

urlpatterns = [
    path("me/", views.me),
    path("google/", views.google_login),
    path("logout/", views.logout),
    path("withdraw/", views.withdraw),
    path("dev-login/", views.dev_login),
    path("extension-tokens/", views.issue_extension_token),
    path("extension-tokens/revoke/", views.revoke_extension_token),
]
