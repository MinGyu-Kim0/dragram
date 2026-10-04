from django.urls import path

from .views import analyze_sentence

urlpatterns = [
    path("sentences/analyze/", analyze_sentence),
]
