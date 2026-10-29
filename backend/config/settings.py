import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "false") == "true"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

# 운영에서만 켠다. 앞단 Caddy가 HTTPS를 끝내고 X-Forwarded-Proto를 넘긴다(infra/).
# backend는 Caddy 뒤에만 열리므로 이 헤더를 믿을 수 있다.
HTTPS = os.environ.get("DJANGO_HTTPS", "false") == "true"
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # .app은 최상위 도메인째 HSTS 사전 등록 목록에 있어 하위 도메인까지 원래 HTTPS 전용이다.
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
# 컨테이너 상태 확인은 Caddy를 거치지 않고 http로 직접 부른다.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "analysis",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "dragram"),
        "USER": os.environ.get("POSTGRES_USER", "dragram"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# 운영 이미지가 빌드할 때 admin 정적 파일을 모으는 곳. 배포가 꺼내 Caddy가 제공한다(infra/).
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

# Google 로그인. 웹 버튼과 같은 OAuth 클라이언트 ID(공개 값)로 ID 토큰의 aud를 검증한다.
# 클라이언트 비밀값은 쓰지 않는다. 비어 있으면 로그인을 거부한다.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
# 로컬 수동 확인용 개발 로그인(이메일만으로 로그인). DEBUG가 아니면 켜도 열리지 않는다.
DEV_LOGIN_ENABLED = os.environ.get("DEV_LOGIN_ENABLED", "false") == "true"

# LLM. 실제 호출할 때만 필요하므로 테스트·CI에서는 비어 있어도 된다.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "")
# 모든 LLM 호출의 기본 추론 강도는 low다(사용자 결정, #217).
OPENAI_REASONING_EFFORT = os.environ.get("OPENAI_REASONING_EFFORT", "low").strip() or "low"
if OPENAI_REASONING_EFFORT not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
    raise ImproperlyConfigured(
        "OPENAI_REASONING_EFFORT must be one of: none, minimal, low, medium, high, xhigh, max."
    )

# 분석 작업 큐(RQ)와 작업자 소식(pub/sub)을 함께 쓰는 Redis(ADR 0005).
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# 테스트 전용. 켜면 분석 작업을 큐에 넣는 자리에서 바로 실행하고, 재매칭 스트림도 요청 스레드에서
# 돌린다. 테스트 트랜잭션 안의 데이터를 같은 DB 연결로 보게 하기 위해서다.
ANALYSIS_INLINE = False
# 사용자별 비용 안전장치(#28, NFR-14). 하루(Asia/Seoul) LLM 토큰 한도와 동시 분석 요청 상한.
ANALYSIS_DAILY_TOKEN_LIMIT = int(os.environ.get("ANALYSIS_DAILY_TOKEN_LIMIT", "200000"))

ANALYSIS_MAX_CONCURRENT = int(os.environ.get("ANALYSIS_MAX_CONCURRENT", "10"))


def _price(name):
    value = os.environ.get(name)
    return float(value) if value else None


# 평가 비용 계산 단가(백만 토큰당 달러, #177). 하나라도 없으면 평가 지표의 비용 칸을 비운다.
EVAL_PRICE_INPUT = _price("EVAL_PRICE_INPUT")
EVAL_PRICE_CACHED_INPUT = _price("EVAL_PRICE_CACHED_INPUT")
EVAL_PRICE_OUTPUT = _price("EVAL_PRICE_OUTPUT")

# 적재한 JMdict 판본 이름(예: "JMdict_e 2026-10-01"). load_jmdict는 이 값이 있어야 적재한다.
JMDICT_EDITION = os.environ.get("JMDICT_EDITION", "")

# LLM이 쓴 새 예문이 원문 키 텍스트(문법 구간 밖)의 연속된 글자를 이만큼 이상 그대로 쓰면 베낀
# 것으로 본다(기호·공백 제외). 실제 예문을 보며 조정한다(#37).
EXAMPLE_COPY_LENGTH = int(os.environ.get("EXAMPLE_COPY_LENGTH", "8"))

REST_FRAMEWORK = {
    # API 비즈니스 오류(errors.BusinessError)를 {"error": code}로 응답한다.
    "EXCEPTION_HANDLER": "errors.handler.handle_exception",
}
