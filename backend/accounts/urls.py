from django.urls import path

from accounts import views

urlpatterns = [
    path("me/", views.me),
    path("google/", views.google_login),
    path("logout/", views.logout),
]
