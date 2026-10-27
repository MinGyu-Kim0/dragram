from django.contrib import admin
from django.urls import include, path

from analysis.connections import connection
from analysis.names import designated_names
from analysis.views import analyze
from config.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/analyses/", analyze),
    path("api/names/", designated_names),
    path("api/grammar-patterns/<int:pattern_id>/connection/", connection),
    path("api/auth/", include("accounts.urls")),
]
