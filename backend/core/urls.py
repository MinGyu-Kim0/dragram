from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("sentences/", views.list_sentences),
    path("sentences/analyze/", views.analyze_sentence),
]
