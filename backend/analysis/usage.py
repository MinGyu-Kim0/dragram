"""분석 요청 하나의 사용 기록(usage_log, FR-A18). 원문은 받지도 남기지도 않는다."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from analysis.models import UsageLog


def today_start():
    """오늘(Asia/Seoul) 자정. 하루 한도와 탈퇴한 계정의 그날 행이 이때부터 센다."""
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def withdrawn_key(user):
    """탈퇴한 Google 계정을 그날 다시 알아보는 값(PR #244). Google 계정 식별자는 남기지 않는다."""
    sub = getattr(user, "google_sub", None)
    if not sub:
        return None
    return salted_hmac("analysis.usage.withdrawn", sub, algorithm="sha256").hexdigest()


def forget(user):
    """탈퇴하는 사용자의 사용량 기록을 지운다. 탈퇴 트랜잭션에서 사용자 행을 잠근 뒤 부른다.

    오늘 행만 계정 연결 대신 withdrawn_key를 남겨, 같은 Google 계정이 그날 다시 가입해도 하루
    한도를 새로 받지 못하게 한다. 한도 계산에 필요한 토큰 수·시각만 두고 분석 연결과 모델은
    비운다(#252). 이 행은 자정이 지나면 purge_withdrawn이 지운다.
    """
    key = withdrawn_key(user)
    if key:
        UsageLog.objects.filter(user=user, created_at__gte=today_start()).update(
            user=None, withdrawn_key=key, analysis=None, model=None
        )
    UsageLog.objects.filter(user=user).delete()
    purge_withdrawn()


def purge_withdrawn():
    """자정이 지난 탈퇴 계정의 행을 지운다. 매일 예약 실행하는 관리 명령(purge_withdrawn_usage)
    외에 분석 요청과 탈퇴 때도 불러, 예약 작업이 밀려도 일찍 지운다(#252).
    """
    UsageLog.objects.filter(withdrawn_key__isnull=False, created_at__lt=today_start()).delete()


def _lock_requester(user):
    """사용자 행을 잠그고, 아직 있으면 그 사용자를 돌려준다. 그사이 탈퇴했으면 None이다(#239).

    탈퇴(같은 행을 잠그고 그 사용자의 기록을 지움)와 차례를 맞춘다. 탈퇴가 먼저면 지워진 사용자를
    가리키는 행을 남기지 않고, 이쪽이 먼저면 탈퇴가 이 행까지 지운다. 트랜잭션 안에서 부른다.
    같은 트랜잭션에서 이 사용자를 가리키는 행을 먼저 쓴 뒤에 부르지 않는다(잠금을 올리다 교착).
    """
    if user is None:
        return None
    return get_user_model().objects.select_for_update(no_key=True).filter(pk=user.pk).first()


class RequestUsage:
    """분석 요청 하나의 request 행과, 그 요청이 부른 LLM 호출의 llm 행들.

    request 행은 처리 경로를 정했을 때 start로 남긴다. llm 행은 호출마다 바로 남겨, 뒤에 분석
    저장이 되돌려져도 남는다. 새 문장은 선점할 때 처리 중 분석 행을 먼저 만들어 잇는다(#98).
    """

    def __init__(self, request):
        self._request = request
        self._user = request.user
        self._withdrawn_key = request.withdrawn_key
        self._analysis_id = request.analysis_id
        self._ids = [request.pk]

    @property
    def user(self):
        """요청한 사용자. 로그인 전 요청이나 탈퇴한 사용자의 요청이면 None이다."""
        return self._user

    @property
    def id(self):
        """request 행 ID. 작업자가 이 기록으로 LLM 호출을 남긴다(#98)."""
        return self._request.pk

    @classmethod
    def resume(cls, usage_id, analysis_id=None):
        """작업자가 요청의 request 행(usage_id)을 불러온다. 요청한 사용자가 그사이 탈퇴해 행이
        지워졌으면(#239) 사용자 없는 request 행으로 새로 잇는다. 같은 작업을 기다리는 다른 요청이
        있을 수 있어 작업은 계속한다.
        """
        # 사용자도 같은 쿼리로 읽는다. 따로 읽으면 그 사이 탈퇴가 커밋됐을 때 사용자를 찾지 못한다.
        request = UsageLog.objects.select_related("user").filter(pk=usage_id).first()
        if request is None:
            return cls.start(UsageLog.Path.LLM, None, analysis_id)
        return cls(request)

    @classmethod
    def start(cls, path, user, analysis_id=None, success=False):
        """처리 경로를 정한 요청의 request 행을 남긴다. user는 요청한 사용자다."""
        purge_withdrawn()
        with transaction.atomic():
            requester = _lock_requester(user)
            key = None if requester else withdrawn_key(user)
            return cls(
                UsageLog.objects.create(
                    kind=UsageLog.Kind.REQUEST,
                    path=path,
                    user=requester,
                    withdrawn_key=key,
                    # 탈퇴한 계정의 행에는 한도 계산에 필요 없는 분석 연결을 남기지 않는다(#252).
                    analysis_id=None if key else analysis_id,
                    success=success,
                )
            )

    def record_llm(
        self,
        *,
        purpose,
        model,
        input_tokens,
        cached_input_tokens,
        output_tokens,
        success,
        attempt=1,
    ):
        """LLM 클라이언트가 보낸 호출마다 부른다. attempt는 시도 차수다(일시 오류로 다시 보낸
        호출은 2, #99).
        """
        with transaction.atomic():
            requester = _lock_requester(self._user)
            # 요청한 사용자가 그사이 탈퇴했으면 그 Google 계정의 그날 사용량으로 남기되, 토큰 수·
            # 시각만 두고 분석 연결과 모델은 비운다(#252).
            key = None if requester else self._withdrawn_key or withdrawn_key(self._user)
            row = UsageLog.objects.create(
                kind=UsageLog.Kind.LLM,
                user=requester,
                withdrawn_key=key,
                analysis_id=None if key else self._analysis_id,
                purpose=purpose,
                model=None if key else model,
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                success=success,
                attempt=attempt,
            )
        self._ids.append(row.pk)

    def succeed(self):
        """요청이 이 경로의 결과를 오류 없이 냈다."""
        UsageLog.objects.filter(pk=self._request.pk).update(success=True)
