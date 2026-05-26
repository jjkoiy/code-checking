"""Style Check Agent — basic style and naming pattern checks."""

from __future__ import annotations

import re
import logging

from app.agents.diff_utils import detect_language, is_code_file, review_text_by_file
from app.agents.evidence_extractor import extract_evidence

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

_SECURITY_TODO_KEYWORDS = (
    "auth",
    "authentication",
    "authorization",
    "permission",
    "role",
    "admin",
    "token",
    "security",
    "credential",
)


def _todo_metadata(line_text: str) -> dict:
    lowered = line_text.lower()
    if any(keyword in lowered for keyword in _SECURITY_TODO_KEYWORDS):
        return {
            "severity": "medium",
            "category": "security",
            "title": "Auth/security TODO left in code",
            "description": "A TODO touches auth or security behavior and should be treated as a caution until resolved.",
            "suggestion": "Resolve the auth/security TODO or link it to a tracked issue with explicit tests for unauthenticated and unauthorized access.",
            "confidence": 0.72,
        }
    return {
        "severity": "low",
        "category": "maintainability",
        "title": "TODO/FIXME left in code",
        "description": "Unresolved TODO or FIXME comment may indicate incomplete work.",
        "suggestion": "Address the item or convert it to a tracked ticket.",
        "confidence": 0.60,
    }


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
                metadata = _todo_metadata(line_text)
                evidence = extract_evidence(diff_text, changed_files, file_path, linenum, linenum)
                findings.append({
                    "agent_name": "style_agent",
                    "severity": metadata["severity"],
                    "category": metadata["category"],
                    "file_path": file_path,
                    "line_number": linenum,
                    "line_start": linenum,
                    "line_end": linenum,
                    "title": metadata["title"],
                    "description": metadata["description"],
                    "evidence": evidence,
                    "suggestion": metadata["suggestion"],
                    "confidence": metadata["confidence"],
                })

    logger.info("Style check produced %d finding(s).", len(findings))
    return findings
