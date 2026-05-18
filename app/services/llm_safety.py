from __future__ import annotations

import re

from app.config import settings


_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (
        re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
        r"\1[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*(?:\\?['\"])?[^\\'\"\s,}]+"),
        r"\1=[REDACTED_SECRET]",
    ),
    (
        re.compile(r"(?i)\b(postgres|postgresql|mysql|mongodb|redis)://[^\s'\",}]+"),
        "[REDACTED_CONNECTION_STRING]",
    ),
]


def llm_mode() -> str:
    if settings.llm_provider == "mock" or not settings.llm_api_key:
        return "mock"
    if not settings.llm_external_enabled:
        return "external_disabled"
    if settings.llm_redaction_enabled:
        return "external_redacted"
    return "external_unredacted"


def external_llm_enabled() -> bool:
    return llm_mode() in {"external_redacted", "external_unredacted"}


def redact_text(text: str) -> str:
    if not settings.llm_redaction_enabled:
        return text

    redacted = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
