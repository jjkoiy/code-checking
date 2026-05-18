"""Style Check Agent — basic style and naming pattern checks."""

from __future__ import annotations

import re
import logging

from app.agents.diff_utils import detect_language, is_code_file, review_text_by_file

logger = logging.getLogger(__name__)

_CHECKS: list[dict] = [
    {
        "id": "ST004",
        "title": "TODO/FIXME left in code",
        "severity": "low",
        "category": "maintainability",
        "description": "Unresolved TODO or FIXME comments may indicate incomplete work.",
        "suggestion": "Address the item or convert it to a tracked ticket.",
    },
]


def _line_number(text: str, match_start: int) -> int:
    return text[:match_start].count("\n") + 1


def check(changed_files: list[dict], diff_text: str = "") -> list[dict]:
    """Run style checks on changed files. Returns list of Finding dicts."""
    findings: list[dict] = []

    languages_by_file = {
        f.get("file_path"): f.get("language")
        for f in changed_files
        if f.get("file_path")
    }
    for file_path, (added_text, line_numbers) in review_text_by_file(diff_text, changed_files).items():
        language = languages_by_file.get(file_path) or detect_language(file_path)
        if not is_code_file(file_path, language):
            continue
        for index, line_text in enumerate(added_text.splitlines()):
            linenum = line_numbers[index] if index < len(line_numbers) else None
            for m in re.finditer(r"\b(?:TODO|FIXME|HACK)\b", line_text):
                findings.append({
                    "agent_name": "style_agent",
                    "severity": "low",
                    "category": "maintainability",
                    "file_path": file_path,
                    "line_number": linenum,
                    "title": "TODO/FIXME left in code",
                    "description": "Unresolved TODO or FIXME comment may indicate incomplete work.",
                    "evidence": line_text[max(0, m.start() - 10):m.end() + 30].strip(),
                    "suggestion": "Address the item or convert it to a tracked ticket.",
                    "confidence": 0.60,
                })

    logger.info("Style check produced %d finding(s).", len(findings))
    return findings
