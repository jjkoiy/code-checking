"""Test Generation Agent stub — P2."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def generate(changed_files: list[dict], aggregated_findings: list[dict],
             llm_findings: list[dict], test_impact: dict) -> dict:
    """Placeholder: return generated tests."""
    # TODO: implement test generation in P2
    return {
        "test_plan": [],
        "generated_tests": [],
        "notes": ["P2 — not implemented"],
    }
