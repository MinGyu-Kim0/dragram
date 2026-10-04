"""Report a fixed failure category without exposing Claude execution output."""

import json
import os
import re
from pathlib import Path


AUTHENTICATION_ERROR = "Authentication failed; renew CLAUDE_CODE_OAUTH_TOKEN."
USAGE_ERROR = "Claude usage limit reached; retry after the limit resets."
BILLING_ERROR = "Claude billing or credit issue; check the subscription."
MODEL_ERROR = "Claude model unavailable; check model access."
UNKNOWN_ERROR = "Claude execution failed; no known error category matched."
UNREADABLE_ERROR = "Claude execution failed; diagnostic output could not be read."

# Match error identifiers or specific failure phrases, never generic topic words.
CATEGORIES = (
    (AUTHENTICATION_ERROR, (
        r"\bauthentication_(?:error|failed)\b",
        r"\b(?:authentication|authorization) (?:failed|failure|error)\b",
        r"\bunauthorized\b|\bnot logged in\b|\binvalid (?:api key|oauth token)\b",
        r"\b(?:oauth|access) token (?:has )?(?:expired|is invalid)\b",
        r"\b(?:http(?: status)?|status(?: code)?|api error)\s*[:=]?\s*401\b",
    )),
    (USAGE_ERROR, (
        r"\brate_limit(?:_error|_exceeded)?\b",
        r"\brate limit(?:ed| exceeded| reached)?\b",
        r"\busage limit (?:reached|exceeded)\b|\bhit your limit\b",
        r"\b(?:http(?: status)?|status(?: code)?|api error)\s*[:=]?\s*429\b",
    )),
    (BILLING_ERROR, (
        r"\bbilling_error\b|\binsufficient_(?:credits?|quota)\b",
        r"\bcredit balance (?:is )?too low\b|\binsufficient credits?\b",
        r"\b(?:billing|payment) (?:failed|failure|error|required)\b",
    )),
    (MODEL_ERROR, (
        r"\bmodel_(?:not_found|not_available|unavailable)\b",
        r"\binvalid model\b|\bmodel (?:is )?(?:unavailable|not found)\b",
    )),
)


def error_text(value):
    """Read supported error fields without stringifying arbitrary message data."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(error_text(item) for item in value)
    if isinstance(value, dict):
        parts = [error_text(value.get(key)) for key in ("type", "code", "message", "error")]
        for key in ("status", "status_code"):
            if value.get(key) in (401, 429, "401", "429"):
                parts.append(f"HTTP {value[key]}")
        return " ".join(parts)
    return ""


def failure_category(messages):
    if not isinstance(messages, list):
        return UNKNOWN_ERROR

    errors = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        subtype = message.get("subtype")
        if message.get("type") == "result" and (
            message.get("is_error") is True
            or isinstance(subtype, str) and subtype.startswith("error_")
        ):
            errors.extend(error_text(message.get(key)) for key in ("subtype", "error", "errors", "result"))
        elif message.get("type") == "assistant" and message.get("error"):
            errors.append(error_text(message["error"]))

    error = " ".join(errors)
    for category, patterns in CATEGORIES:
        if any(re.search(pattern, error, re.IGNORECASE) for pattern in patterns):
            return category
    return UNKNOWN_ERROR


def report_failure(path):
    try:
        messages = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        category = UNREADABLE_ERROR
    else:
        category = failure_category(messages)
    print(f"::error::{category}")


if __name__ == "__main__":
    report_failure(os.environ.get("EXECUTION_FILE", ""))
