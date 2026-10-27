"""접속 형태는 공용 지식으로 저장하고, 없는 정보만 별도로 채운다(#229)."""

from datetime import timedelta

import pytest
import redis
from django.test import Client
from django.utils import timezone

from analysis import jobs, review
from analysis.connections import run_connection
from analysis.models import GrammarPattern, UsageLog
from errors import AnalysisError, BusinessError
from tests.analysis.helpers import Analyzed, analyze, connected_client, new_pattern, pattern_form
from tests.analysis.test_worker import _work_burst

pytestmark = pytest.mark.django_db

FORM = "동사 て형 + いる"


def registered(client, fake_llm, form=FORM):
    fake_llm.response = {
        "translation_ko": "먹고 있습니다",
        "new_patterns": [{**new_pattern((1, "lemma"), (2, "lemma")), "connection_form": form}],
    }
    response = analyze(client, "食べています")
    return GrammarPattern.objects.get(), response


def test_new_pattern_keeps_connection_from_the_existing_call(client, fake_llm):
    pattern, response = registered(client, fake_llm)

    [item] = response.json()["grammar"]
    assert item["connection"] == {
        "pattern_id": pattern.pk,
        "text": FORM,
        "review_status": "pending",
        "filled": True,
    }
    assert pattern.connection_form == FORM
    assert len(fake_llm.all_requests()) == 1

    cached = analyze(client, "食べています")

    assert cached.json()["grammar"] == [item]
    assert len(fake_llm.all_requests()) == 1


def connection(client, pattern):
    return Analyzed(client.post(f"/api/grammar-patterns/{pattern.pk}/connection/"))


def missing(client, fake_llm):
    pattern, _ = registered(client, fake_llm)
    GrammarPattern.objects.filter(pk=pattern.pk).update(
        connection_form=None, connection_filled=False, connection_status=None
    )
    fake_llm.forget_requests()
    return pattern


def test_missing_connection_is_generated_once_without_original_text(client, fake_llm, analyst):
    pattern = missing(client, fake_llm)
    fake_llm.connection_response = {"connection_form": FORM}

    cached = analyze(client, "食べています").json()["grammar"][0]
    assert cached["explanation_ko"] == "동작이 이어지고 있음을 나타낸다"
    assert not cached["connection"]["filled"]
    assert fake_llm.all_requests() == []

    first = connection(client, pattern)

    assert first.json() == {
        "pattern_id": pattern.pk,
        "text": FORM,
        "review_status": "pending",
        "filled": True,
    }
    assert len(fake_llm.connection_requests) == 1
    assert "食べています" not in str(fake_llm.connection_requests)
    assert connection(client, pattern).json() == first.json()
    assert len(fake_llm.connection_requests) == 1
    log = UsageLog.objects.get(purpose="pattern_connection")
    assert log.user == analyst
    assert log.success


def test_concurrent_readers_share_one_job(client, fake_llm, monkeypatch):
    pattern = missing(client, fake_llm)
    queued = []
    monkeypatch.setattr(jobs, "enqueue_connection", lambda *args: queued.append(args))
    path = f"/api/grammar-patterns/{pattern.pk}/connection/"

    first = client.post(path)
    second = client.post(path)

    assert len(queued) == 1
    assert fake_llm.connection_requests == []
    run_connection(*queued[0])
    assert Analyzed(first).json()["text"] == FORM
    assert Analyzed(second).json()["text"] == FORM
    assert len(fake_llm.connection_requests) == 1


def test_failed_generation_can_retry_without_changing_the_usage(client, fake_llm):
    pattern = missing(client, fake_llm)
    before = list(pattern.usages.values())
    fake_llm.connection_error = BusinessError(AnalysisError.FAILED, "테스트 오류")

    assert connection(client, pattern).json() == {"type": "error", "error": "ANALYSIS:FAILED"}
    pattern.refresh_from_db()
    assert not pattern.connection_filled
    assert pattern.connection_started_at is None
    assert list(pattern.usages.values()) == before

    fake_llm.connection_error = None
    assert connection(client, pattern).json()["text"] == FORM
    assert len(fake_llm.connection_requests) == 2


@pytest.mark.parametrize("form", ["", 1, "동사 ⟨N1⟩", "a" * 256, "동사\x00"])
def test_bad_generated_connection_is_not_saved(client, fake_llm, form):
    pattern = missing(client, fake_llm)
    fake_llm.connection_response = {"connection_form": form}

    assert connection(client, pattern).json()["error"] == "ANALYSIS:FAILED"
    pattern.refresh_from_db()
    assert not pattern.connection_filled


def test_no_known_connection_is_saved_without_repeated_calls(client, fake_llm):
    pattern = missing(client, fake_llm)
    fake_llm.connection_response = {"connection_form": None}

    first = connection(client, pattern).json()

    assert first["text"] is None
    assert first["review_status"] is None
    assert first["filled"]
    assert connection(client, pattern).json() == first
    assert len(fake_llm.connection_requests) == 1


@pytest.mark.parametrize("form", ["食べています", "동사 ⟨N1⟩", "a" * 256])
def test_first_response_does_not_store_a_quote_or_invalid_connection(client, fake_llm, form):
    pattern, response = registered(client, fake_llm, form)

    assert pattern.connection_form is None
    assert response.json()["grammar"][0]["connection"]["text"] is None


def test_missing_connection_obeys_auth_and_quota_but_cached_information_is_available(
    client, fake_llm, settings
):
    pattern = missing(client, fake_llm)
    assert connection(Client(), pattern).status_code == 401
    settings.ANALYSIS_DAILY_TOKEN_LIMIT = 1
    assert connection(client, pattern).json()["error"] == "ANALYSIS:USAGE_LIMIT"
    assert fake_llm.connection_requests == []
    GrammarPattern.objects.filter(pk=pattern.pk).update(
        connection_form=FORM, connection_filled=True, connection_status="pending"
    )
    assert connection(client, pattern).json()["text"] == FORM


def test_rejected_pattern_cannot_generate_or_return_connection(client, fake_llm):
    pattern = missing(client, fake_llm)
    review.reject_pattern(pattern)

    assert connection(client, pattern).status_code == 404
    assert fake_llm.connection_requests == []


@pytest.mark.parametrize("change", [{"name": "ている（変更）"}, {"status": "approved"}])
def test_changed_pattern_discards_the_in_flight_result(client, fake_llm, change):
    pattern = missing(client, fake_llm)
    fake_llm.before_connection = lambda: GrammarPattern.objects.filter(pk=pattern.pk).update(
        **change
    )

    assert connection(client, pattern).json()["error"] == "ANALYSIS:FAILED"
    pattern.refresh_from_db()
    assert not pattern.connection_filled


def test_replaced_lease_cannot_be_cleared_by_an_old_job(client, fake_llm):
    pattern = missing(client, fake_llm)
    newer = timezone.now()
    fake_llm.before_connection = lambda: GrammarPattern.objects.filter(pk=pattern.pk).update(
        connection_started_at=newer
    )

    assert connection(client, pattern).json()["error"] == "ANALYSIS:FAILED"
    pattern.refresh_from_db()
    assert pattern.connection_started_at == newer
    assert not pattern.connection_filled


def test_admin_correction_wins_over_a_running_generation(client, fake_llm, admin_client):
    pattern = missing(client, fake_llm)

    def edit():
        pattern.refresh_from_db()
        response = admin_client.post(
            f"/admin/analysis/grammarpattern/{pattern.pk}/change/",
            pattern_form(pattern, connection_form="동사 て형 + いる (관리자)"),
        )
        assert response.status_code == 302

    fake_llm.before_connection = edit
    result = connection(client, pattern).json()

    assert result["text"] == "동사 て형 + いる (관리자)"
    assert result["review_status"] == "approved"


def test_approved_pattern_can_review_new_connection_separately(client, fake_llm, admin_client):
    pattern = missing(client, fake_llm)
    GrammarPattern.objects.filter(pk=pattern.pk).update(status="approved")
    assert connection(client, pattern).json()["review_status"] == "pending"

    response = admin_client.post(
        "/admin/analysis/grammarpattern/",
        {"action": "approve_connection", "_selected_action": str(pattern.pk)},
    )

    assert response.status_code == 302
    assert connection(client, pattern).json()["review_status"] == "approved"


def test_pattern_approval_includes_existing_connection(client, fake_llm):
    pattern, _ = registered(client, fake_llm)
    pattern.test_cases.append({"text": "雨が降る", "should_match": False})
    pattern.save(update_fields=["test_cases"])

    review.approve_pattern(pattern)

    assert connection(client, pattern).json()["review_status"] == "approved"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_queue_worker_fills_once_for_two_waiting_responses(settings, fake_llm, redis_db):
    client = connected_client()
    pattern = missing(client, fake_llm)
    settings.ANALYSIS_INLINE = False
    path = f"/api/grammar-patterns/{pattern.pk}/connection/"

    first = client.post(path)
    second = client.post(path)
    assert fake_llm.connection_requests == []
    assert jobs.Queue(jobs.QUEUE_NAME, connection=redis_db).count == 1
    _work_burst()

    assert Analyzed(first).json()["text"] == FORM
    assert Analyzed(second).json()["text"] == FORM
    assert len(fake_llm.connection_requests) == 1
    assert not redis_db.keys("rq:job:*")


def test_failed_enqueue_releases_the_lease(client, fake_llm, monkeypatch, settings):
    pattern = missing(client, fake_llm)
    settings.ANALYSIS_INLINE = False

    def failed(*args, **kwargs):
        raise redis.ConnectionError("테스트 오류")

    monkeypatch.setattr(jobs.Queue, "enqueue", failed)

    assert connection(client, pattern).status_code == 502
    pattern.refresh_from_db()
    assert pattern.connection_started_at is None
    assert fake_llm.connection_requests == []


def test_expired_job_can_be_replaced(client, fake_llm):
    pattern = missing(client, fake_llm)
    GrammarPattern.objects.filter(pk=pattern.pk).update(
        connection_started_at=timezone.now() - timedelta(seconds=jobs.REMATCH_LOCK_SECONDS + 1)
    )

    assert connection(client, pattern).json()["text"] == FORM
    assert len(fake_llm.connection_requests) == 1
