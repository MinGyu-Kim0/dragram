from django.contrib import admin
from django.urls import include, path

from analysis.names import designated_names
from analysis.views import analyze
from config.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/analyses/", analyze),
    path("api/names/", designated_names),
    path("api/auth/", include("accounts.urls")),
]
