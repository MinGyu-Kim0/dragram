"""Regression coverage for safe Claude action failure diagnostics."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import claude_failure


class FailureCategoryTests(unittest.TestCase):
    def test_failed_result_errors_array_identifies_action_failures(self):
        cases = (
            ("OAuth token has expired. Please obtain a new token.", claude_failure.AUTHENTICATION_ERROR),
            ("API Error: 429 Too Many Requests", claude_failure.USAGE_ERROR),
            ("Your credit balance is too low to access the API.", claude_failure.BILLING_ERROR),
            ("The model is unavailable.", claude_failure.MODEL_ERROR),
        )
        for error, expected in cases:
            with self.subTest(error=error):
                messages = [{"type": "result", "subtype": "error_during_execution", "errors": [error]}]
                self.assertEqual(claude_failure.failure_category(messages), expected)

    def test_error_flag_takes_precedence_over_success_subtype(self):
        messages = [{
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "API Error: 401 Invalid API key",
        }]
        self.assertEqual(claude_failure.failure_category(messages), claude_failure.AUTHENTICATION_ERROR)

    def test_assistant_error_identifies_authentication_failure(self):
        for error in ("authentication_failed", {"type": "authentication_error", "message": "Token rejected"}):
            with self.subTest(error=error):
                messages = [{"type": "assistant", "error": error}]
                self.assertEqual(claude_failure.failure_category(messages), claude_failure.AUTHENTICATION_ERROR)

    def test_structured_error_fields_identify_categories(self):
        cases = (
            ({"type": "rate_limit_error"}, claude_failure.USAGE_ERROR),
            ({"code": "insufficient_credits"}, claude_failure.BILLING_ERROR),
            ({"message": "Invalid model"}, claude_failure.MODEL_ERROR),
            ({"status": 401}, claude_failure.AUTHENTICATION_ERROR),
            ({"status_code": "429"}, claude_failure.USAGE_ERROR),
            ({"error": {"type": "model_not_found"}}, claude_failure.MODEL_ERROR),
        )
        for error, expected in cases:
            with self.subTest(error=error):
                messages = [{"type": "result", "is_error": True, "errors": [error]}]
                self.assertEqual(claude_failure.failure_category(messages), expected)

    def test_http_error_context_distinguishes_status_from_identifiers(self):
        for error, expected in (
            ("HTTP 401 Unauthorized", claude_failure.AUTHENTICATION_ERROR),
            ("status code: 429", claude_failure.USAGE_ERROR),
            ("Rate limit exceeded", claude_failure.USAGE_ERROR),
        ):
            with self.subTest(error=error):
                messages = [{"type": "result", "is_error": True, "result": error}]
                self.assertEqual(claude_failure.failure_category(messages), expected)

    def test_successful_review_and_tool_content_do_not_become_failures(self):
        review = "Review authentication_failed, rate_limit_error, billing_error and model_not_found handling."
        messages = [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": review}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": review},
            {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": review}]}},
        ]
        self.assertEqual(claude_failure.failure_category(messages), claude_failure.UNKNOWN_ERROR)

    def test_actual_failure_is_not_overridden_by_successful_review_text(self):
        messages = [
            {"type": "result", "subtype": "success", "result": "API Error: 401 handling is correct."},
            {"type": "result", "subtype": "error_during_execution", "errors": ["Usage limit reached"]},
        ]
        self.assertEqual(claude_failure.failure_category(messages), claude_failure.USAGE_ERROR)

    def test_generic_topics_and_numeric_identifiers_are_not_error_categories(self):
        for error in (
            "The review of the model, credit, payment and oauth modules could not finish.",
            "Could not finish reviewing rate limit handling in the application.",
            "Process exited with request 401 and record 429 pending.",
            "API Error: 1401; status code: 4290",
            "Request identifiers: 1401, 4290, 401234, 142900",
        ):
            with self.subTest(error=error):
                messages = [{"type": "result", "is_error": True, "result": error}]
                self.assertEqual(claude_failure.failure_category(messages), claude_failure.UNKNOWN_ERROR)

    def test_arbitrary_error_metadata_does_not_become_error_text(self):
        messages = [{
            "type": "result",
            "is_error": True,
            "error": {"request_id": 401, "metadata": "authentication_failed", "review": "billing_error"},
        }]
        self.assertEqual(claude_failure.failure_category(messages), claude_failure.UNKNOWN_ERROR)

    def test_malformed_messages_are_ignored_without_crashing(self):
        for messages in (
            None,
            {},
            {"type": "result", "is_error": True, "result": "authentication_failed"},
            [],
            [None, 401, True, "authentication_failed", [], {}],
            [{"type": "result", "is_error": "true", "subtype": None, "result": "authentication_failed"}],
            [{"type": "assistant", "error": None}],
            [{"type": "assistant", "error": {}}],
        ):
            with self.subTest(messages=messages):
                self.assertEqual(claude_failure.failure_category(messages), claude_failure.UNKNOWN_ERROR)


class FailureReportTests(unittest.TestCase):
    def assert_report(self, path, expected):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            claude_failure.report_failure(path)
        self.assertEqual(stdout.getvalue(), f"::error::{expected}\n")
        self.assertEqual(stderr.getvalue(), "")

    def test_report_does_not_print_tokens_review_text_or_execution_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-execution-session.json"
            messages = [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Private source code"}]}},
                {"type": "result", "is_error": True, "errors": ["API Error: 401 token=private-test-token\n::warning::injected"]},
            ]
            path.write_text(json.dumps(messages), encoding="utf-8")
            self.assert_report(path, claude_failure.AUTHENTICATION_ERROR)

    def test_unrecognized_failure_emits_only_static_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.json"
            path.write_text(json.dumps([{"type": "result", "is_error": True, "result": "private-test-token"}]), encoding="utf-8")
            self.assert_report(path, claude_failure.UNKNOWN_ERROR)

    def test_missing_empty_malformed_and_invalid_utf8_files_use_static_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_report(Path(directory) / "missing-private-path.json", claude_failure.UNREADABLE_ERROR)
            self.assert_report("", claude_failure.UNREADABLE_ERROR)
            self.assert_report(directory, claude_failure.UNREADABLE_ERROR)
            path = Path(directory) / "execution.json"
            for contents in (b"", b'{"secret": "private-test-token",', b"\xff\xfeprivate-test-token"):
                with self.subTest(contents=contents):
                    path.write_bytes(contents)
                    self.assert_report(path, claude_failure.UNREADABLE_ERROR)

    def test_valid_json_with_unexpected_schema_uses_static_unknown_category(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.json"
            for messages in ({"secret": "private-test-token"}, None, [None, "authentication_failed", 401]):
                with self.subTest(messages=messages):
                    path.write_text(json.dumps(messages), encoding="utf-8")
                    self.assert_report(path, claude_failure.UNKNOWN_ERROR)

    def test_cli_reads_execution_file_environment_and_handles_missing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.json"
            path.write_text(json.dumps([{"type": "assistant", "error": "rate_limit_error"}]), encoding="utf-8")
            for execution_file, expected in ((str(path), claude_failure.USAGE_ERROR), (None, claude_failure.UNREADABLE_ERROR)):
                with self.subTest(execution_file=execution_file):
                    env = os.environ.copy()
                    env.pop("EXECUTION_FILE", None)
                    if execution_file is not None:
                        env["EXECUTION_FILE"] = execution_file
                    result = subprocess.run(
                        [sys.executable, str(Path(claude_failure.__file__).resolve())],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, f"::error::{expected}\n")
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
