from errors.base import error_domain

DesignatedNameError = error_domain(
    "NAME",
    {
        # 표기가 없거나 50자를 넘거나, 읽기에 가나가 아닌 글자가 있거나 50자를 넘는다(#136).
        "INVALID": 400,
        # 사용자 한 명이 지정할 수 있는 표기 수(analysis.names.MAX_NAMES)에 닿았다.
        "TOO_MANY": 409,
    },
)
