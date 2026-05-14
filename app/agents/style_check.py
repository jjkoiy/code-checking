"""Style Check Agent — basic style and naming pattern checks."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_CHECKS: list[dict] = [
    {
        "id": "ST001",
        "title": "Overly long line",
        "severity": "low",
        "category": "style",
        "description": "Lines longer than 120 characters reduce readability.",
        "suggestion": "Break the line into multiple lines or extract intermediate variables.",
    },
    {
        "id": "ST002",
        "title": "Magic number used",
        "severity": "low",
        "category": "maintainability",
        "description": "Numeric literals without a named constant obscure intent.",
        "suggestion": "Extract the value into a named constant (e.g., MAX_RETRIES = 3).",
    },
    {
        "id": "ST003",
        "title": "Single-letter variable name",
        "severity": "low",
        "category": "readability",
        "description": "Single-letter names (except common loop vars like i, j) are hard to understand.",
        "suggestion": "Use a descriptive name that conveys the variable's purpose.",
    },
    {
        "id": "ST004",
        "title": "TODO/FIXME left in code",
        "severity": "low",
        "category": "maintainability",
        "description": "Unresolved TODO or FIXME comments may indicate incomplete work.",
        "suggestion": "Address the item or convert it to a tracked ticket.",
    },
    {
        "id": "ST005",
        "title": "Function appears too long",
        "severity": "medium",
        "category": "maintainability",
        "description": "Very long functions are hard to test and understand. (Heuristic: > 50 lines in diff chunk)",
        "suggestion": "Consider extracting helper functions for logical sub-steps.",
    },
]


def _line_number(text: str, match_start: int) -> int:
    return text[:match_start].count("\n") + 1


def check(changed_files: list[dict], diff_text: str = "") -> list[dict]:
    """Run style checks on changed files. Returns list of Finding dicts."""
    findings: list[dict] = []

    for f_info in changed_files:
        content = f_info.get("content", "")
        file_path = f_info.get("file_path", "")

        # Check for TODO/FIXME in the diff text
        if diff_text:
            for m in re.finditer(r"\b(?:TODO|FIXME|HACK)\b", diff_text):
                linenum = _line_number(diff_text, m.start())
                findings.append({
                    "agent_name": "style_agent",
                    "severity": "low",
                    "category": "maintainability",
                    "file_path": file_path,
                    "line_number": linenum,
                    "title": "TODO/FIXME left in code",
                    "description": "Unresolved TODO or FIXME comment may indicate incomplete work.",
                    "evidence": diff_text[max(0, m.start() - 10):m.end() + 30].strip(),
                    "suggestion": "Address the item or convert it to a tracked ticket.",
                    "confidence": 0.60,
                })

    logger.info("Style check produced %d finding(s).", len(findings))
    return findings
