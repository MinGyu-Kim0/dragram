from django.urls import path

from .views import list_sentences

urlpatterns = [
    path("sentences/", list_sentences),
]
