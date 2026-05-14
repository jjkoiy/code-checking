"""Security Scan Agent stub — P1."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def scan(diff_text: str, changed_files: list[dict]) -> list[dict]:
    """Placeholder: return security findings."""
    # TODO: implement security pattern scanning in P1
    return []
