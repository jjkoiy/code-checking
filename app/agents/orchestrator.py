"""LangGraph Orchestrator — builds and runs the multi-agent review pipeline."""

from __future__ import annotations

import json
import logging
import traceback
from typing import Optional

from langgraph.graph import StateGraph, END

from app.models.state import ReviewState
from app.agents import context_builder, static_analysis, style_check
from app.agents import security_scan, finding_aggregator, llm_review
from app.agents import test_impact, test_generation, validation, report

logger = logging.getLogger(__name__)


def _merge_changed_files(existing: list[dict], parsed: list[dict]) -> list[dict]:
    """Merge parsed diff metadata without dropping request-provided fields like content."""
    if not parsed:
        return existing

    existing_by_path = {item.get("file_path"): item for item in existing if item.get("file_path")}
    parsed_paths = {item.get("file_path") for item in parsed}
    merged: list[dict] = []

    for parsed_item in parsed:
        file_path = parsed_item.get("file_path")
        combined = dict(existing_by_path.get(file_path, {}))
        combined.update(parsed_item)
        merged.append(combined)

    merged.extend(
        item for item in existing
        if item.get("file_path") and item.get("file_path") not in parsed_paths
    )
    return merged


# ── Node functions ────────────────────────────────────────────────

def _context_builder_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: context_builder")
    state["status"] = "context_building"
    try:
        state["changed_files"] = _merge_changed_files(
            existing=state.get("changed_files", []),
            parsed=context_builder.parse_diff(state.get("diff_text", "")),
        )
        ctx = context_builder.build_context(
            diff_text=state.get("diff_text", ""),
            changed_files=state.get("changed_files", []),
        )
        state["project_context"] = ctx
        state["status"] = "context_ready"
    except Exception as e:
        logger.error("Context builder failed: %s", e)
        state["errors"].append({"agent": "context_builder", "error": str(e)})
        state["status"] = "context_error"
    return state


def _static_analysis_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: static_analysis")
    state["status"] = "static_analysis"
    try:
        findings = static_analysis.analyze(
            diff_text=state.get("diff_text", ""),
            changed_files=state.get("changed_files", []),
        )
        state["static_findings"] = findings
    except Exception as e:
        logger.error("Static analysis failed: %s", e)
        state["errors"].append({"agent": "static_analysis", "error": str(e)})
        state["static_findings"] = []
    return state


def _style_check_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: style_check")
    state["status"] = "style_check"
    try:
        findings = style_check.check(
            changed_files=state.get("changed_files", []),
            diff_text=state.get("diff_text", ""),
        )
        state["style_findings"] = findings
    except Exception as e:
        logger.error("Style check failed: %s", e)
        state["errors"].append({"agent": "style_check", "error": str(e)})
        state["style_findings"] = []
    return state


def _security_scan_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: security_scan")
    state["status"] = "security_scan"
    try:
        findings = security_scan.scan(
            diff_text=state.get("diff_text", ""),
            changed_files=state.get("changed_files", []),
        )
        state["security_findings"] = findings
    except Exception as e:
        logger.error("Security scan failed: %s", e)
        state["errors"].append({"agent": "security_scan", "error": str(e)})
        state["security_findings"] = []
    return state


def _test_impact_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: test_impact")
    state["status"] = "test_impact"
    try:
        result = test_impact.analyze(
            changed_files=state.get("changed_files", []),
            diff_text=state.get("diff_text", ""),
        )
        state["test_impact"] = result
    except Exception as e:
        logger.error("Test impact analysis failed: %s", e)
        state["errors"].append({"agent": "test_impact", "error": str(e)})
        state["test_impact"] = {}
    return state


def _finding_aggregator_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: aggregating")
    state["status"] = "aggregating"
    try:
        all_raw = (
            state.get("static_findings", [])
            + state.get("style_findings", [])
            + state.get("security_findings", [])
        )
        aggregated = finding_aggregator.aggregate(all_raw)
        state["aggregated_findings"] = aggregated
    except Exception as e:
        logger.error("Aggregator failed: %s", e)
        state["errors"].append({"agent": "finding_aggregator", "error": str(e)})
        state["aggregated_findings"] = []
    return state


def _llm_review_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: llm_review")
    state["status"] = "llm_review"
    try:
        findings = llm_review.review(
            diff_text=state.get("diff_text", ""),
            changed_files=state.get("changed_files", []),
            aggregated_findings=state.get("aggregated_findings", []),
            project_context=state.get("project_context", {}),
        )
        state["llm_findings"] = findings
    except Exception as e:
        logger.error("LLM review failed: %s", e)
        state["errors"].append({"agent": "llm_review", "error": str(e)})
        state["llm_findings"] = []
    return state


def _test_generation_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: test_generation")
    state["status"] = "test_generation"
    try:
        result = test_generation.generate(
            changed_files=state.get("changed_files", []),
            aggregated_findings=state.get("aggregated_findings", []),
            llm_findings=state.get("llm_findings", []),
            test_impact=state.get("test_impact", {}),
        )
        state["test_generation_result"] = result
    except Exception as e:
        logger.error("Test generation failed: %s", e)
        state["errors"].append({"agent": "test_generation", "error": str(e)})
        state["test_generation_result"] = {}
    return state


def _validation_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: validation")
    state["status"] = "validation"
    try:
        result = validation.validate(
            generated_tests=state.get("test_generation_result", {}),
        )
        state["validation_result"] = result
    except Exception as e:
        logger.error("Validation failed: %s", e)
        state["errors"].append({"agent": "validation", "error": str(e)})
        state["validation_result"] = {"status": "not_run", "errors": []}
    return state


def _report_node(state: ReviewState) -> ReviewState:
    logger.info("Stage: report")
    state["status"] = "report_generating"
    try:
        result = report.generate(
            aggregated_findings=state.get("aggregated_findings", []),
            llm_findings=state.get("llm_findings", []),
            test_generation_result=state.get("test_generation_result", {}),
            validation_result=state.get("validation_result", {}),
        )
        if state.get("errors"):
            result.setdefault("json_report", {})["error"] = "One or more review stages failed."
            result["json_report"]["pipeline_errors"] = state["errors"]
            result["markdown_report"] += "\n## Pipeline Errors\n\n"
            for err in state["errors"]:
                result["markdown_report"] += f"- **{err.get('agent', 'unknown')}**: {err.get('error', '')}\n"
        state["final_report"] = result
        state["status"] = "failed" if state.get("errors") else "completed"
    except Exception as e:
        logger.error("Report generation failed: %s", e)
        state["errors"].append({"agent": "report", "error": str(e)})
        state["status"] = "failed"
        state["final_report"] = {
            "summary": f"Report generation failed: {e}",
            "markdown_report": f"# Error\n\nReport generation failed: {e}",
            "json_report": {"error": str(e)},
        }
    return state


# ── Conditional routing ───────────────────────────────────────────

def _should_run_security(state: ReviewState) -> str:
    return "security_scan"


# ── Graph construction ────────────────────────────────────────────

def build_review_graph():
    """Build and compile the LangGraph StateGraph for the review pipeline.

    Flow (P1, sequential — parallel analysis deferred to later phase):
        context_builder → static_analysis → style_check → security_scan
        → test_impact → finding_aggregator → llm_review
        → test_generation (P2 stub) → validation (P2 stub) → report
    """
    graph = StateGraph(ReviewState)

    graph.add_node("context_builder", _context_builder_node)
    graph.add_node("static_analysis", _static_analysis_node)
    graph.add_node("style_check", _style_check_node)
    graph.add_node("security_scan", _security_scan_node)
    graph.add_node("test_impact", _test_impact_node)
    graph.add_node("finding_aggregator", _finding_aggregator_node)
    graph.add_node("llm_review", _llm_review_node)
    graph.add_node("test_generation", _test_generation_node)
    graph.add_node("validation", _validation_node)
    graph.add_node("report", _report_node)

    graph.set_entry_point("context_builder")

    # Sequential chain for P1 (avoids concurrent-write reducer complexity)
    graph.add_edge("context_builder", "static_analysis")
    graph.add_edge("static_analysis", "style_check")
    graph.add_edge("style_check", "security_scan")
    graph.add_edge("security_scan", "test_impact")
    graph.add_edge("test_impact", "finding_aggregator")
    graph.add_edge("finding_aggregator", "llm_review")
    graph.add_edge("llm_review", "test_generation")
    graph.add_edge("test_generation", "validation")
    graph.add_edge("validation", "report")
    graph.add_edge("report", END)

    return graph.compile()


# ── Entry point ───────────────────────────────────────────────────

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_review_graph()
    return _graph


def run_review_pipeline(task_id: str, state: ReviewState) -> dict:
    """Run the full review pipeline via LangGraph. Returns the final report dict."""
    state["task_id"] = task_id
    if "errors" not in state:
        state["errors"] = []

    logger.info("Starting review pipeline for task=%s", task_id)
    try:
        graph = _get_graph()
        final_state = graph.invoke(state)
        logger.info("Pipeline completed for task=%s, status=%s", task_id, final_state.get("status"))
        return final_state.get("final_report", {})
    except Exception as e:
        logger.error("Pipeline execution failed for task=%s: %s", task_id, e)
        traceback.print_exc()
        return {
            "summary": f"Pipeline execution failed: {e}",
            "markdown_report": f"# Error\n\nPipeline execution failed: {e}",
            "json_report": {"error": str(e)},
        }
