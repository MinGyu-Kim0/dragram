"""분석 요청 하나의 사용 기록(usage_log, FR-A18). 원문은 받지도 남기지도 않는다."""

from analysis.models import UsageLog


class RequestUsage:
    """분석 요청 하나의 request 행과, 그 요청이 부른 LLM 호출의 llm 행들.

    request 행은 처리 경로를 정했을 때 start로 남긴다. llm 행은 호출마다 바로 남겨, 뒤에 분석
    저장이 되돌려져도 남는다. 분석 행이 아직 없으면(새 문장) 저장할 때 link로 잇는다.
    """

    def __init__(self, request):
        self._request = request
        self._analysis_id = request.analysis_id
        self._ids = [request.pk]

    @classmethod
    def start(cls, path, analysis_id=None, success=False):
        """처리 경로를 정한 요청의 request 행을 남긴다."""
        return cls(
            UsageLog.objects.create(
                kind=UsageLog.Kind.REQUEST, path=path, analysis_id=analysis_id, success=success
            )
        )

    def record_llm(
        self, *, purpose, model, input_tokens, cached_input_tokens, output_tokens, success
    ):
        """LLM 클라이언트가 보낸 호출마다 부른다. 재시도는 하지 않아 시도 차수는 1이다."""
        row = UsageLog.objects.create(
            kind=UsageLog.Kind.LLM,
            analysis_id=self._analysis_id,
            purpose=purpose,
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            success=success,
            attempt=1,
        )
        self._ids.append(row.pk)

    def link(self, analysis):
        """아직 분석에 잇지 않은 이 요청의 기록을 analysis에 잇는다. 저장 트랜잭션 안에서 불러,
        저장이 되돌려지면 잇기도 되돌려진다.
        """
        UsageLog.objects.filter(pk__in=self._ids, analysis__isnull=True).update(analysis=analysis)

    def succeed(self):
        """요청이 이 경로의 결과를 오류 없이 냈다."""
        UsageLog.objects.filter(pk=self._request.pk).update(success=True)
