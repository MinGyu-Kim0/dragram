from errors.base import error_domain

ExtensionError = error_domain(
    "EXTENSION",
    {
        # 확장 버전이 서버의 최소 확장 버전보다 낮거나 알 수 없다(#349). 확장과의 약속이다.
        # 확장 연결(토큰)은 그대로 두므로, 업데이트하면 다시 로그인하지 않고 쓸 수 있다.
        "UPDATE_REQUIRED": 426,
    },
)
