from django.urls import include, path

from .health import health

urlpatterns = [
    path("api/health/", health),
    path("api/", include("apps.analysis.urls")),
    path("api/", include("apps.library.urls")),
]
