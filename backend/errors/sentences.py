from errors.base import error_domain

UserSentenceError = error_domain(
    "SENTENCE",
    {
        # 내 기록에 그 문장이 없다. 남의 기록 ID도 같은 응답이라 있는지 알 수 없다(#196, #195).
        "NOT_FOUND": 404,
        # 기록이 가리키는 공용 분석이 지금 원문의 키와 다르다(정규화 규칙이 바뀌어 재연결 전).
        # 확장에서 다시 분석하면 볼 수 있다(#195).
        "OUTDATED": 409,
    },
)
