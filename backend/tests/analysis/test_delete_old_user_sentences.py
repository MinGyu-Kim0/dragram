"""예전 자동 저장 기록을 지우는 마이그레이션(#325)."""

import hashlib
from importlib import import_module

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils import timezone

from analysis.models import SentenceAnalysis, UserSentence
from tests.analysis.helpers import connected_client

pytestmark = pytest.mark.django_db


def test_migration_deletes_old_records_but_keeps_shared_analyses():
    connected_client("me")
    analysis = SentenceAnalysis.objects.create(
        sentence_hash="0" * 64,
        normalize_version=1,
        normalized_length=3,
        status=SentenceAnalysis.Status.COMPLETE,
        word_spans=[],
    )
    UserSentence.objects.create(
        user=get_user_model().objects.get(username="me"),
        original_hash=hashlib.sha256("猫だ。".encode()).hexdigest(),
        original_text="猫だ。",
        analysis=analysis,
        last_analyzed_at=timezone.now(),
    )
    migration = import_module("analysis.migrations.0030_delete_old_user_sentences")

    migration.delete_old_records(apps, None)

    assert not UserSentence.objects.exists()
    assert SentenceAnalysis.objects.filter(pk=analysis.pk).exists()
