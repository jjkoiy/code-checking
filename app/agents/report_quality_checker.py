"""Deterministic report quality checks before final output."""

from __future__ import annotations

import re
from collections import Counter


_SEVERITIES = ("critical", "high", "medium", "low", "info")
_TEMPLATE_TEST_PHRASES = (
    "Changed file should have regression coverage",
    "pytest.skip",
)


def _compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _finding_signature(finding: dict) -> tuple:
    return (
        finding.get("file_path"),
        finding.get("line_start") or finding.get("line_number"),
        finding.get("line_end") or finding.get("line_number"),
        finding.get("rule_family") or _compact(finding.get("title")),
    )


def _bad_evidence(evidence: str) -> bool:
    if not evidence or "\ufffd" in evidence or "\u0431\u043a" in evidence:
        return True
    compact = _compact(evidence)
    if " except " in compact and " pass " in compact and "\n" not in evidence:
        return True
    if " pass query " in compact or " pass sql " in compact:
        return True
    return False


def check_report_quality(report: dict) -> list[dict]:
    """Return structured quality warnings; callers may include them in final output."""
    warnings: list[dict] = []
    findings = report.get("findings", [])
    counts = Counter(finding.get("severity") for finding in findings)

    for severity in _SEVERITIES:
        expected = counts.get(severity, 0)
        actual = report.get(f"{severity}_count", 0)
        if actual != expected:
            warnings.append({
                "code": "severity_count_mismatch",
                "message": f"{severity}_count={actual} does not match findings={expected}.",
            })

    blocking_count = sum(1 for finding in findings if finding.get("blocking") is True)
    if report.get("blocking_count", 0) != blocking_count:
        warnings.append({
            "code": "blocking_count_mismatch",
            "message": "blocking_count does not match finding blocking flags.",
        })

    signatures = [_finding_signature(finding) for finding in findings]
    if len(signatures) != len(set(signatures)):
        warnings.append({
            "code": "duplicate_findings",
            "message": "Report contains duplicate findings at the same location and rule family.",
        })

    for index, finding in enumerate(findings):
        if finding.get("severity") not in _SEVERITIES:
            warnings.append({
                "code": "invalid_severity",
                "finding_index": index,
                "message": f"Invalid severity: {finding.get('severity')}",
            })
        if not isinstance(finding.get("blocking"), bool):
            warnings.append({
                "code": "invalid_blocking",
                "finding_index": index,
                "message": "blocking must be a boolean.",
            })
        if _bad_evidence(str(finding.get("evidence", ""))):
            warnings.append({
                "code": "bad_evidence",
                "finding_index": index,
                "message": "Evidence is empty, corrupted, or appears to be incorrectly concatenated.",
            })

    suggestion_text = "\n".join(
        str(item.get("risk_covered", "")) + "\n" + str(item.get("assertion_direction", ""))
        for item in report.get("test_suggestions", [])
    )
    generated_text = "\n".join(
        str(item.get("code", ""))
        for item in report.get("generated_tests", [])
    )
    for phrase in _TEMPLATE_TEST_PHRASES:
        if phrase in suggestion_text or phrase in generated_text:
            warnings.append({
                "code": "template_test_suggestion",
                "message": f"Test suggestion still contains template phrase: {phrase}",
            })

    markdown = str(report.get("markdown_report", ""))
    if "\ufffd" in markdown or "\u0431\u043a" in markdown:
        warnings.append({
            "code": "encoding_artifact",
            "message": "Report contains mojibake or replacement characters.",
        })

    return warnings
