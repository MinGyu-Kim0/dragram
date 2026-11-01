from errors.base import error_domain

MyItemError = error_domain(
    "MY_ITEM",
    {
        # 종류·ID·상태·예문이 맞지 않거나, 없거나 반려된 용법·뜻이다(#322).
        "INVALID": 400,
        # 내 예문에 없다. 남의 예문 ID도 같은 응답이라 있는지 알 수 없다.
        "NOT_FOUND": 404,
        # 사용자 한 명이 둘 수 있는 항목·예문 수(analysis.my_items)에 닿았다.
        "TOO_MANY": 409,
    },
)
