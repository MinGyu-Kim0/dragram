import os
import subprocess
import sys

import pytest

from tests.test_deploy_settings import BACKEND_DIR, PRODUCTION_ENV


def _stderr_after(code, debug):
    """settings.LOGGING을 적용한 새 프로세스에서 code를 실행하고 표준 오류를 돌려준다."""
    env = {**os.environ, **PRODUCTION_ENV, "DJANGO_DEBUG": debug}
    result = subprocess.run(
        [sys.executable, "-c", f"import django, logging; django.setup(); {code}"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stderr


REQUEST_ERROR = (
    "try:\n    raise ValueError('boom')\n"
    "except ValueError:\n"
    "    logging.getLogger('django.request').error('Internal Server Error: /api/x', exc_info=True)"
)


@pytest.mark.parametrize("debug", ["false", "true"])
def test_unhandled_request_error_traceback_goes_to_stderr_once(debug):
    stderr = _stderr_after(f"exec({REQUEST_ERROR!r})", debug)

    assert stderr.count("Traceback (most recent call last)") == 1
    assert "ValueError: boom" in stderr


def test_analysis_timing_line_is_written_once():
    stderr = _stderr_after(
        "logging.getLogger('analysis.timing').info('{\"event\": \"t\"}')", "false"
    )

    assert stderr.splitlines() == ['{"event": "t"}']
