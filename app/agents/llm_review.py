"""LLM Review Agent stub — P1."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def review(diff_text: str, changed_files: list[dict],
           aggregated_findings: list[dict], project_context: dict) -> list[dict]:
    """Placeholder: return LLM deep review findings."""
    # TODO: implement LLM call in P1
    return []
