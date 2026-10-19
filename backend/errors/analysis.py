from errors.base import error_domain

AnalysisError = error_domain(
    "ANALYSIS",
    {
        # 분석할 문장이 없다(빈 문자열, 정규화 후 빈 문장, UTF-8로 못 바꾸는 문자열).
        "TEXT_REQUIRED": 400,
        # 외부 의존(형태소 분석, LLM)이 실패했거나 LLM 응답이 검증을 통과하지 못했다.
        "FAILED": 502,
    },
)
