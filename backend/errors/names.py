from errors.base import error_domain

DesignatedNameError = error_domain(
    "NAME",
    {
        # 표기가 없거나 50자를 넘거나, 읽기에 가나가 아닌 글자가 있거나 50자를 넘는다(#136).
        "INVALID": 400,
    },
)
