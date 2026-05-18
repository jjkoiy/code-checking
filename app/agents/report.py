"""Report Agent — generates Markdown and JSON review reports."""

from __future__ import annotations

import logging

from app.models.report import ReportGenerationResultModel, ReviewReportModel

logger = logging.getLogger(__name__)

_SEVERITY_ICON = {
    "critical": "[CRITICAL]",
    "high": "[HIGH]",
    "medium": "[MEDIUM]",
    "low": "[LOW]",
}


def _format_finding_md(f: dict) -> str:
    badge = _SEVERITY_ICON.get(f.get("severity", "low"), "[LOW]")
    blocking = " **[BLOCKING]**" if f.get("blocking") else ""
    lines = [
        f"### {badge}: {f.get('title', 'No title')}{blocking}",
        f"",
        f"- **Category**: {f.get('category', 'N/A')}",
        f"- **File**: `{f.get('file_path') or 'N/A'}`",
        f"- **Line**: {f.get('line_number') or 'N/A'}",
        f"- **Confidence**: {f.get('confidence', 0):.0%}",
        f"- **Source**: {', '.join(f.get('source_agents', ['unknown']))}",
        f"",
        f"**Description**: {f.get('description', 'N/A')}",
        f"",
    ]
    if f.get("evidence"):
        lines.append(f"**Evidence**: `{f['evidence']}`")
        lines.append("")
    if f.get("suggestion"):
        lines.append(f"**Suggestion**: {f['suggestion']}")
        lines.append("")
    if f.get("attack_scenario"):
        lines.append(f"**Attack Scenario**: {f['attack_scenario']}")
        lines.append("")
    return "\n".join(lines)


def _format_languages(languages: list[str]) -> str:
    return ", ".join(sorted(language for language in languages if language)) or "unknown"


def _build_merge_recommendation(
    blocking_count: int,
    critical_count: int,
    high_count: int,
    medium_count: int,
    has_reviewable_content: bool = True,
) -> dict:
    if not has_reviewable_content:
        return {
            "status": "caution",
            "label": "No reviewable content",
            "reason": (
                "The review did not receive diff lines or changed file content, "
                "so the result should not be treated as a clean pass."
            ),
        }
    if blocking_count or critical_count:
        return {
            "status": "block",
            "label": "Do not merge yet",
            "reason": (
                "Resolve blocking or critical findings before merging. "
                "These issues may introduce security, reliability, or correctness risk."
            ),
        }
    if high_count:
        return {
            "status": "needs_review",
            "label": "Human review required",
            "reason": "High severity findings remain and should be reviewed before merge.",
        }
    if medium_count:
        return {
            "status": "caution",
            "label": "Merge with caution",
            "reason": "Medium severity findings remain; merge only if the team accepts the risk.",
        }
    return {
        "status": "pass",
        "label": "No blocking concerns",
        "reason": "No blocking, critical, high, or medium severity findings were detected.",
    }


def generate(aggregated_findings: list[dict], llm_findings: list[dict],
             test_generation_result: dict, validation_result: dict,
             llm_mode: str = "mock",
             validation_warnings: list[dict] | None = None,
             metadata: dict | None = None,
             review_scope: dict | None = None) -> dict:
    """Generate Markdown and JSON report from final normalized findings."""
    all_findings = list(aggregated_findings)
    validation_warnings = validation_warnings or []
    metadata = metadata or {
        "agent_count": 0,
        "duration_seconds": None,
        "llm_mode": llm_mode,
        "pipeline_status": "completed",
    }
    review_scope = review_scope or {
        "file_count": 0,
        "languages": [],
        "mode": "added_lines_only",
        "has_reviewable_content": True,
    }

    # Categorize
    blocking = [f for f in all_findings if f.get("blocking")]
    non_blocking = [f for f in all_findings if not f.get("blocking")]
    critical = [f for f in non_blocking if f.get("severity") == "critical"]
    high = [f for f in non_blocking if f.get("severity") == "high"]
    medium = [f for f in non_blocking if f.get("severity") == "medium"]
    low = [f for f in non_blocking if f.get("severity") == "low"]
    high_risk_findings = blocking + critical + high

    total = len(all_findings)
    has_reviewable_content = review_scope.get("has_reviewable_content", True)
    merge_recommendation = _build_merge_recommendation(
        blocking_count=len(blocking),
        critical_count=len(critical),
        high_count=len(high),
        medium_count=len(medium),
        has_reviewable_content=has_reviewable_content,
    )
    if has_reviewable_content:
        summary = (
            f"Review complete. {total} finding(s): "
            f"{len(blocking)} blocking; non-blocking severity: {len(critical)} critical, "
            f"{len(high)} high, {len(medium)} medium, {len(low)} low."
        )
    else:
        summary = (
            "Review completed without reviewable content. "
            "Provide a unified diff or changed file content to receive meaningful findings."
        )

    # Build Markdown report
    md: list[str] = [
        "# Code Review Report",
        "",
        f"## Summary",
        "",
        summary,
        "",
        "## Merge Recommendation",
        "",
        f"**{merge_recommendation['label']}** — {merge_recommendation['reason']}",
        "",
        f"- **LLM mode**: `{llm_mode}`",
        "",
        "## Review Scope",
        "",
        f"- **Files**: {review_scope.get('file_count', 0)}",
        f"- **Languages**: {_format_languages(review_scope.get('languages', []))}",
        f"- **Mode**: {review_scope.get('mode', 'added_lines_only')}",
        f"- **Added lines**: {review_scope.get('added_lines', 'unknown')}",
        "",
        "---",
        "",
    ]

    if high_risk_findings:
        md.append("## High-Risk Summary")
        md.append("")
        for f in high_risk_findings[:5]:
            location = f"{f.get('file_path') or 'N/A'}:{f.get('line_number') or 'N/A'}"
            md.append(
                f"- **{f.get('severity', 'low').upper()}** "
                f"{f.get('title', 'No title')} (`{location}`)"
            )
        if len(high_risk_findings) > 5:
            md.append(f"- ...and {len(high_risk_findings) - 5} more high-risk finding(s).")
        md.append("")
        md.append("---")
        md.append("")

    if blocking:
        md.append("## Blocking Issues")
        md.append("")
        for f in blocking:
            md.append(_format_finding_md(f))
        md.append("---")
        md.append("")

    if critical:
        md.append("## Critical")
        md.append("")
        for f in critical:
            md.append(_format_finding_md(f))
        md.append("---")
        md.append("")

    if high:
        md.append("## High Severity")
        md.append("")
        for f in high:
            md.append(_format_finding_md(f))
        md.append("---")
        md.append("")

    if medium:
        md.append("## Medium Severity")
        md.append("")
        for f in medium:
            md.append(_format_finding_md(f))
        md.append("---")
        md.append("")

    if low:
        md.append("## Low Severity")
        md.append("")
        for f in low:
            md.append(_format_finding_md(f))
        md.append("---")
        md.append("")

    if not all_findings:
        if has_reviewable_content:
            md.append("[OK] No issues found in this review.")
        else:
            md.append("[WARN] No reviewable content was available for this review.")
        md.append("")

    # Test generation summary
    test_plan = test_generation_result.get("test_plan", [])
    generated_tests = test_generation_result.get("generated_tests", [])
    if test_plan:
        md.append("## Test Suggestions")
        md.append("")
        for t in test_plan:
            md.append(f"- **{t.get('name', 'Unnamed')}**: {t.get('risk_covered', '')} ({t.get('test_type', 'unit')})")
        md.append("")
        md.append("---")
        md.append("")

    if generated_tests:
        md.append("## Generated Test Drafts")
        md.append("")
        for generated in generated_tests:
            md.append(f"### {generated.get('name', 'Unnamed test')}")
            md.append("")
            md.append(f"- **Target**: `{generated.get('target_file', 'N/A')}`")
            md.append(f"- **Framework**: {generated.get('framework', 'N/A')}")
            md.append(f"- **Executed**: {generated.get('executed', False)}")
            if generated.get("code"):
                md.append("")
                md.append("```python")
                md.append(generated["code"].rstrip())
                md.append("```")
            md.append("")
        md.append("---")
        md.append("")

    if validation_result:
        md.append("## Validation")
        md.append("")
        md.append(f"- **Status**: {validation_result.get('status', 'not_run')}")
        errors = validation_result.get("errors", [])
        if errors:
            md.append(f"- **Errors**: {len(errors)}")
        md.append("")

    if validation_warnings:
        md.append("## Finding Validation Warnings")
        md.append("")
        for warning in validation_warnings:
            md.append(
                f"- **{warning.get('agent', 'unknown')}**: {warning.get('error', '')}"
            )
        md.append("")

    md.append("*Generated by Agent Review System v0.1*")
    md.append("")

    markdown_report = "\n".join(md)

    json_report = ReviewReportModel.model_validate({
        "summary": summary,
        "metadata": metadata,
        "review_scope": review_scope,
        "llm_mode": llm_mode,
        "total_findings": total,
        "blocking_count": len(blocking),
        "critical_count": len(critical),
        "high_count": len(high),
        "medium_count": len(medium),
        "low_count": len(low),
        "merge_recommendation": merge_recommendation,
        "high_risk_findings": high_risk_findings,
        "findings": all_findings,
        "test_suggestions": test_plan,
        "generated_tests": generated_tests,
        "validation_result": validation_result,
        "validation_warnings": validation_warnings,
    }).model_dump()

    logger.info("Report generated: %d findings.", total)
    return ReportGenerationResultModel.model_validate({
        "summary": summary,
        "markdown_report": markdown_report,
        "json_report": json_report,
    }).model_dump()
