from errors.base import error_domain

AuthError = error_domain(
    "AUTH",
    {
        # Google ID 토큰이 없거나 검증(서명, 만료, aud, iss)을 통과하지 못했다.
        "GOOGLE_TOKEN_INVALID": 401,
        # Google 계정의 이메일이 인증되지 않았다.
        "EMAIL_NOT_VERIFIED": 403,
        # 관리자가 막은 계정이다(is_active 거짓).
        "ACCOUNT_DISABLED": 403,
        # 상태를 바꾸는 요청에 CSRF 값이 없거나 맞지 않는다.
        "CSRF_FAILED": 403,
        # Google 공개 키를 받아 오지 못했다.
        "GOOGLE_UNAVAILABLE": 502,
        # 개발 로그인에 이메일이 아닌 값을 보냈다.
        "DEV_EMAIL_INVALID": 400,
        # 서버에 Google 클라이언트 ID가 설정되지 않았다.
        "LOGIN_UNAVAILABLE": 503,
    },
)
