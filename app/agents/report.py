"""Report Agent stub — P1."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def generate(aggregated_findings: list[dict], llm_findings: list[dict],
             test_generation_result: dict, validation_result: dict) -> dict:
    """Placeholder: return markdown + json report."""
    # TODO: implement real report generation in P1
    return {
        "summary": "P0 placeholder report.",
        "markdown_report": "# Review Report\n\n*No analysis in P0.*",
        "json_report": {"findings": [], "tests": []},
    }
