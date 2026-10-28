from errors.base import error_domain

UserSentenceError = error_domain(
    "SENTENCE",
    {
        # 내 기록에 그 문장이 없다. 남의 기록 ID도 같은 응답이라 있는지 알 수 없다(#196).
        "NOT_FOUND": 404,
    },
)
