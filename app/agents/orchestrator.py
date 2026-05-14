"""
LangGraph Orchestrator — placeholder for P0.

In a future phase this will be replaced with a real StateGraph that sequences:
ContextBuilder → [StaticAnalysis, StyleCheck, SecurityScan, TestImpact]
→ FindingAggregator → LLMReview → TestGeneration → Validation → Report.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.models.state import ReviewState

logger = logging.getLogger(__name__)


def build_review_graph():
    """Placeholder — returns None for now, real LangGraph graph in P1+."""
    logger.info("LangGraph orchestrator not yet implemented — using sequential fallback.")
    return None


def run_review_pipeline(task_id: str, state: ReviewState) -> dict:
    """
    Sequential no-op pipeline for P0.
    Each step is a stub that passes state through unchanged.
    Returns a placeholder final report dict.
    """
    logger.info("Starting review pipeline for task=%s (no-op stubs)", task_id)

    _context_builder(state)
    _static_analysis(state)
    _style_check(state)
    _security_scan(state)
    _test_impact(state)
    _finding_aggregator(state)
    _llm_review(state)
    _test_generation(state)
    _validation(state)
    report = _report(state)

    logger.info("Review pipeline completed for task=%s", task_id)
    return report


# ── Stub node implementations ───────────────────────────────────

def _context_builder(state: ReviewState) -> None:
    state["status"] = "context_building"
    state["project_context"] = {}
    # TODO: implement parse diff, detect language, retrieve from Chroma


def _static_analysis(state: ReviewState) -> None:
    state["status"] = "static_analysis"
    state["static_findings"] = []
    # TODO: implement AST/regex/linter analysis


def _style_check(state: ReviewState) -> None:
    state["status"] = "style_check"
    state["style_findings"] = []
    # TODO: implement naming/style checks


def _security_scan(state: ReviewState) -> None:
    state["status"] = "security_scan"
    state["security_findings"] = []
    # TODO: implement security pattern scanning


def _test_impact(state: ReviewState) -> None:
    state["status"] = "test_impact"
    state["test_impact"] = {}
    # TODO: implement test impact analysis


def _finding_aggregator(state: ReviewState) -> None:
    state["status"] = "aggregating"
    state["aggregated_findings"] = []
    # TODO: implement dedup + severity normalization


def _llm_review(state: ReviewState) -> None:
    state["status"] = "llm_review"
    state["llm_findings"] = []
    # TODO: implement LLM deep review


def _test_generation(state: ReviewState) -> None:
    state["status"] = "test_generation"
    state["test_generation_result"] = {}
    # TODO: implement test generation


def _validation(state: ReviewState) -> None:
    state["status"] = "validation"
    state["validation_result"] = {"status": "not_run", "errors": []}
    # TODO: implement test validation


def _report(state: ReviewState) -> dict:
    state["status"] = "report_generating"
    placeholder_report = {
        "summary": "P0 placeholder — no real analysis performed.",
        "markdown_report": "# Review Report\n\n*No analysis available in P0 mode.*",
        "json_report": {"findings": [], "tests": []},
    }
    state["final_report"] = placeholder_report
    state["status"] = "completed"
    return placeholder_report
