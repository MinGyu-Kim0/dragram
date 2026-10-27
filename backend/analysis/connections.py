"""문법 접속 형태를 요청한 뒤 따로 채운다. 원문은 받지 않는다(#229)."""

import asyncio
import json
import time
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.tokens import ExtensionTokenAuthentication
from analysis import jobs, limits, llm, patterns, stream
from analysis.answers import connection_form
from analysis.models import GrammarPattern, ReviewStatus, UsageLog
from analysis.usage import RequestUsage
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error


def item(pattern):
    return {
        "pattern_id": pattern.pk,
        "text": pattern.connection_form,
        "review_status": pattern.connection_status,
        "filled": pattern.connection_filled,
    }


def _get(pattern_id):
    pattern = GrammarPattern.objects.select_related("variant_of").filter(pk=pattern_id).first()
    if pattern is None or any(
        p.status == ReviewStatus.REJECTED for p in (pattern, pattern.variant_of) if p is not None
    ):
        raise BusinessError(AnalysisError.PATTERN_UNAVAILABLE, "사용할 수 없는 문법")
    return pattern


@api_view(["POST"])
@authentication_classes([ExtensionTokenAuthentication])
@permission_classes([])
def connection(request, pattern_id):
    from analysis.views import _leaving

    leave = limits.enter(request.user)
    try:
        started, usage = None, None
        with transaction.atomic():
            pattern = _get(pattern_id)
            patterns.lock_links()
            pattern = patterns.lock_families(pattern)[pattern_id]
            _get(pattern_id)
            if pattern.connection_filled:
                leave()
                return Response(item(pattern))
            now = timezone.now()
            if (
                pattern.connection_started_at is None
                or pattern.connection_started_at
                <= now - timedelta(seconds=jobs.REMATCH_LOCK_SECONDS)
            ):
                if limits.over_limit(request.user):
                    raise BusinessError(AnalysisError.USAGE_LIMIT, "하루 토큰 한도를 넘음")
                started = now
                pattern.connection_started_at = started
                pattern.save(update_fields=["connection_started_at"])
                usage = RequestUsage.start(UsageLog.Path.LLM, request.user)
        if started is not None:
            try:
                jobs.enqueue_connection(pattern_id, started, usage.id)
            except BusinessError:
                _release(pattern_id, started)
                raise
        return StreamingHttpResponse(
            _leaving(_wait(pattern_id), leave), content_type="application/json"
        )
    except BaseException:
        leave()
        raise


async def _wait(pattern_id):
    deadline = time.monotonic() + stream.WAIT_SECONDS
    try:
        while time.monotonic() < deadline:
            pattern = await sync_to_async(_get)(pattern_id)
            if pattern.connection_filled:
                yield json.dumps(item(pattern), ensure_ascii=False)
                return
            if pattern.connection_started_at is None:
                break
            await asyncio.sleep(0.25)
        raise BusinessError(AnalysisError.FAILED, "문법 접속 형태를 받지 못함")
    except BusinessError as error:
        log_business_error(error)
        yield json.dumps({"type": "error", "error": error.error_code.code})


def _release(pattern_id, started):
    GrammarPattern.objects.filter(pk=pattern_id, connection_started_at=started).update(
        connection_started_at=None
    )


def run_connection(pattern_id, started, usage_id):
    """기존 RQ 작업자에서 실행한다. 만료된 시도와 관리자가 고친 정보는 덮지 않는다."""
    try:
        pattern = _get(pattern_id)
        if (
            pattern.connection_filled
            or pattern.connection_started_at != started
            or started <= timezone.now() - timedelta(seconds=jobs.REMATCH_LOCK_SECONDS)
        ):
            return
        basis = (pattern.name, pattern.morpheme_key, pattern.variant_of_id, pattern.status)
        usage = RequestUsage(UsageLog.objects.get(pk=usage_id))
        result = llm.get_client(usage.record_llm).fill_connection(
            {
                "pattern_name": pattern.name,
                "morphemes": [c._asdict() for c in patterns.conditions_of(pattern)],
                "usages": list(
                    (pattern.variant_of or pattern)
                    .usages.exclude(status=ReviewStatus.REJECTED)
                    .values("name", "explanation_ko")
                ),
            }
        )
        if not isinstance(result, dict) or "connection_form" not in result:
            raise BusinessError(AnalysisError.FAILED, "접속 형태 응답이 없음")
        raw = result["connection_form"]
        form = connection_form(raw)
        if raw is not None and form is None:
            raise BusinessError(AnalysisError.FAILED, "접속 형태 응답 검증 실패")
        with transaction.atomic():
            patterns.lock_links()
            current = patterns.lock_families(pattern)[pattern_id]
            _get(pattern_id)
            if (
                current.connection_started_at != started
                or current.connection_filled
                or basis
                != (current.name, current.morpheme_key, current.variant_of_id, current.status)
            ):
                return
            current.connection_form = form
            current.connection_filled = True
            current.connection_status = patterns.filled_status(form)
            current.save(
                update_fields=["connection_form", "connection_filled", "connection_status"]
            )
        usage.succeed()
    except BusinessError as error:
        log_business_error(error)
    finally:
        _release(pattern_id, started)
