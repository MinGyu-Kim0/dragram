from errors.base import error_domain

AnalysisError = error_domain(
    "ANALYSIS",
    {
        # 분석할 문장이 없다(빈 문자열, 정규화 후 빈 문장, UTF-8로 못 바꾸는 문자열).
        "TEXT_REQUIRED": 400,
        # 원문이 글자 수 상한(analysis.views.MAX_TEXT_LENGTH)을 넘는다.
        "TEXT_TOO_LONG": 413,
        "PATTERN_UNAVAILABLE": 404,
        # 외부 의존(형태소 분석, LLM)이 실패했거나 LLM 응답이 검증을 통과하지 못했다.
        "FAILED": 502,
        # 오늘 쓸 수 있는 LLM 토큰을 다 써서 LLM을 새로 부를 수 없다(#28).
        "USAGE_LIMIT": 429,
        # 그 사용자가 동시에 처리 중인 분석 요청이 상한에 닿았다(#28).
        "TOO_MANY_REQUESTS": 429,
    },
)
