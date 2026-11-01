from django.contrib import admin
from django.urls import include, path

from analysis.connections import connection
from analysis.my_items import my_example, my_items
from analysis.my_japanese import my_grammar, my_words
from analysis.names import designated_names
from analysis.views import analyze
from config.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/analyses/", analyze),
    path("api/names/", designated_names),
    path("api/my-items/", my_items),
    path("api/my-examples/<int:example_id>/", my_example),
    path("api/my-japanese/grammar/", my_grammar),
    path("api/my-japanese/words/", my_words),
    path("api/grammar-patterns/<int:pattern_id>/connection/", connection),
    path("api/auth/", include("accounts.urls")),
]
