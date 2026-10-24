"""사용자별 비용 안전장치(#28, NFR-14): 하루 LLM 토큰 한도. 원문은 다루지 않는다."""

from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from analysis.models import UsageLog


def today_tokens(user):
    """오늘(Asia/Seoul 자정부터) 그 사용자의 llm 행 입력+출력 토큰 합. NULL은 0이다."""
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    tokens = Coalesce("input_tokens", 0) + Coalesce("output_tokens", 0)
    rows = UsageLog.objects.filter(kind=UsageLog.Kind.LLM, user=user, created_at__gte=midnight)
    return rows.aggregate(total=Coalesce(Sum(tokens), 0))["total"]


def over_limit(user):
    """LLM을 새로 부르면 안 되는가. 이미 큐에 들어간 작업은 막지 않아 한도를 조금 넘을 수 있다."""
    return today_tokens(user) >= settings.ANALYSIS_DAILY_TOKEN_LIMIT
