import os
import subprocess
import sys
from pathlib import Path

from django.test import override_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 운영 compose(infra/compose.yaml)가 backend에 넘기는 값과 같은 모양이다.
PRODUCTION_ENV = {
    "DJANGO_SECRET_KEY": "x" * 60 + "production-only-test-value",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "dragram.app",
    "DJANGO_HTTPS": "true",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://dragram.app",
}


def test_production_settings_pass_deploy_checks():
    env = {**os.environ, **PRODUCTION_ENV}

    result = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@override_settings(SECURE_SSL_REDIRECT=True)
def test_health_answers_over_plain_http_when_https_redirect_is_on(client):
    # 컨테이너 상태 확인은 Caddy를 거치지 않고 http로 직접 부른다.
    assert client.get("/api/health/").status_code == 200
    assert client.get("/api/names/").status_code == 301
