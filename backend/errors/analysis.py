from errors.base import BusinessError


class TextRequired(BusinessError):
    """분석할 문장이 없다(빈 문자열, 정규화 후 빈 문장, UTF-8로 못 바꾸는 문자열)."""

    code = "text_required"
    status = 400


class AnalysisFailed(BusinessError):
    """외부 의존(형태소 분석, LLM)이 실패했거나 LLM 응답이 검증을 통과하지 못했다."""

    code = "analysis_failed"
    status = 502
