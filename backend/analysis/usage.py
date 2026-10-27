"""분석 요청 하나의 사용 기록(usage_log, FR-A18). 원문은 받지도 남기지도 않는다."""

from django.contrib.auth import get_user_model
from django.db import transaction

from analysis.models import UsageLog


def _requester(user):
    """기록에 남길 사용자. 그사이 탈퇴했으면 None이다(#239).

    사용자 행을 잠가 탈퇴(같은 행을 잠그고 그 사용자의 기록을 지움)와 차례를 맞춘다. 탈퇴가 먼저면
    지워진 사용자를 가리키는 행을 남기지 않고, 이쪽이 먼저면 탈퇴가 이 행까지 지운다.
    트랜잭션 안에서 부른다.
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
        self._analysis_id = request.analysis_id
        self._ids = [request.pk]

    @property
    def id(self):
        """request 행 ID. 작업자가 이 기록으로 LLM 호출을 남긴다(#98)."""
        return self._request.pk

    @classmethod
    def start(cls, path, user, analysis_id=None, success=False):
        """처리 경로를 정한 요청의 request 행을 남긴다. user는 요청한 사용자다."""
        with transaction.atomic():
            return cls(
                UsageLog.objects.create(
                    kind=UsageLog.Kind.REQUEST,
                    path=path,
                    user=_requester(user),
                    analysis_id=analysis_id,
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
            row = UsageLog.objects.create(
                kind=UsageLog.Kind.LLM,
                user=_requester(self._user),
                analysis_id=self._analysis_id,
                purpose=purpose,
                model=model,
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
