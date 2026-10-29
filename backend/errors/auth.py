from errors.base import error_domain

AuthError = error_domain(
    "AUTH",
    {
        # 로그인이 필요하다: 로그인하지 않은 웹 세션, 또는 확장 토큰이 없거나 모르거나 만료·폐기됨.
        # 확장과의 약속이다(#109).
        "LOGIN_REQUIRED": 401,
        # Google ID 토큰이 없거나 검증(서명, 만료, aud, iss)을 통과하지 못했다.
        "GOOGLE_TOKEN_INVALID": 401,
        # Google 계정의 이메일이 인증되지 않았다.
        "EMAIL_NOT_VERIFIED": 403,
        # 가입하기에 이용약관 동의(agree_terms가 참)가 없다(#257).
        "TERMS_NOT_AGREED": 400,
        # 가입하기 전에 이 세션에서 검증한 Google 로그인이 없거나 10분이 지났다(#257).
        "SIGNUP_EXPIRED": 401,
        # 관리자가 막은 계정이다(is_active 거짓).
        "ACCOUNT_DISABLED": 403,
        # 탈퇴를 확인한 계정과 지금 세션의 계정이 다르다(다른 탭에서 다른 계정으로 로그인함 등).
        # 가입하기도 가입 화면에 보인 계정과 기다리는 가입의 계정이 다르면 이 코드로 거부한다.
        "ACCOUNT_MISMATCH": 409,
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
