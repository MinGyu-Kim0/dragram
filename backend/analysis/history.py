"""분석 기록(user_sentence): 사용자가 분석한 문장의 원문을 본인 기록에 남긴다(#93)."""

import hashlib
import logging

from django.db import DatabaseError, transaction
from django.utils import timezone

from analysis.models import UserSentence

logger = logging.getLogger(__name__)


def record(user, original, analysis_id):
    """결과가 저장된 공용 분석(analysis_id)을 응답에 보낸 뒤 그 사용자의 기록을 남긴다.

    같은 원문이면 행을 새로 만들지 않고 가리키는 분석과 마지막 분석일시를 바꾼다(동시 요청도
    한 문장으로 끝나는 upsert). 저장에 실패해도 보낸 응답은 그대로 두고, 원문 없이 로그만 남긴다.
    """
    now = timezone.now()
    try:
        with transaction.atomic():
            UserSentence.objects.bulk_create(
                [
                    UserSentence(
                        user=user,
                        original_hash=hashlib.sha256(original.encode()).hexdigest(),
                        original_text=original,
                        analysis_id=analysis_id,
                        created_at=now,
                        last_analyzed_at=now,
                    )
                ],
                update_conflicts=True,
                unique_fields=["user", "original_hash"],
                update_fields=["analysis", "last_analyzed_at"],
            )
    except DatabaseError as e:
        logger.warning(
            "분석 기록 저장 실패: analysis_id=%s error=%s", analysis_id, type(e).__name__
        )
