import os
import subprocess
import sys

import pytest

from tests.test_deploy_settings import BACKEND_DIR, PRODUCTION_ENV


def _stderr_after(code, debug):
    """settings.LOGGING을 적용한 새 프로세스에서 code를 실행하고 표준 오류를 돌려준다."""
    env = {**os.environ, **PRODUCTION_ENV, "DJANGO_DEBUG": debug}
    result = subprocess.run(
        [sys.executable, "-c", f"import django, logging\ndjango.setup()\n{code}"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stderr


def _request_error(message):
    """처리하지 못한 예외를 Django처럼 django.request에 남긴다. DB 오류처럼 원인 예외를 잇는다."""
    # traceback이 보여 주는 raise 줄에 메시지가 없도록 변수로 둔다.
    return (
        f"message = {message!r}\n"
        "try:\n    try:\n        raise ValueError(message)\n"
        "    except ValueError as e:\n        raise RuntimeError(message) from e\n"
        "except RuntimeError:\n"
        "    logging.getLogger('django.request').error('Internal Server Error', exc_info=True)"
    )


@pytest.mark.parametrize("debug", ["false", "true"])
def test_unhandled_request_error_traceback_goes_to_stderr_once(debug):
    stderr = _stderr_after(_request_error("boom"), debug)

    assert stderr.count("Traceback (most recent call last)") == 2
    assert "RuntimeError: boom" in stderr


# PostgreSQL 제약 위반의 DETAIL은 실패한 행을 통째로 싣는다. 원문에는 줄바꿈도, traceback의
# 예외 연결 문구도 들어갈 수 있다.
DB_ERROR = (
    'null value in column "x"\nDETAIL:  Failing row contains (1, 원문 첫 줄\n\n'
    "The above exception was the direct cause of the following exception:\n\n둘째 줄)."
)


def test_db_error_detail_with_user_text_is_not_logged():
    stderr = _stderr_after(_request_error(DB_ERROR), "false")

    assert "원문" not in stderr
    assert "둘째 줄" not in stderr
    assert 'RuntimeError: null value in column "x"' in stderr
    assert stderr.count("The above exception was the direct cause") == 1


def test_db_error_detail_in_worker_failure_message_is_not_logged():
    # RQ는 작업 예외의 traceback을 except 블록 안에서 메시지 본문에 담아 남긴다.
    stderr = _stderr_after(
        f"import traceback\nmessage = {DB_ERROR!r}\n"
        "try:\n    raise ValueError(message)\n"
        "except ValueError:\n"
        "    logging.getLogger('rq.worker').error('job failed\\n%s', traceback.format_exc())",
        "false",
    )

    assert "원문" not in stderr
    assert "둘째 줄" not in stderr
    assert 'ValueError: null value in column "x"' in stderr


def test_analysis_timing_line_is_written_once():
    stderr = _stderr_after(
        "logging.getLogger('analysis.timing').info('{\"event\": \"t\"}')", "false"
    )

    assert stderr.splitlines() == ['{"event": "t"}']


def test_django_info_is_not_written_in_production():
    stderr = _stderr_after("logging.getLogger('django.request').info('quiet')", "false")

    assert stderr == ""
