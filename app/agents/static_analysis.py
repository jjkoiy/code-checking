"""Static Analysis Agent — pattern-based code analysis without LLM."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_CHECKS: list[dict] = [
    {
        "id": "SA001",
        "title": "Bare except clause",
        "severity": "medium",
        "category": "bug",
        "pattern": re.compile(r"except\s*:", re.MULTILINE),
        "description": "Bare 'except:' catches system-exiting exceptions (KeyboardInterrupt, SystemExit).",
        "suggestion": "Catch specific exception types, or at minimum 'except Exception'.",
    },
    {
        "id": "SA002",
        "title": "Empty except block",
        "severity": "medium",
        "category": "bug",
        "pattern": re.compile(r"except[^:]*:\s*\n\s*(?:pass|\.\.\.)\s*$", re.MULTILINE),
        "description": "Empty except block silently swallows errors, making debugging difficult.",
        "suggestion": "At minimum log the exception; consider re-raising or handling it explicitly.",
    },
    {
        "id": "SA003",
        "title": "Mutable default argument",
        "severity": "medium",
        "category": "bug",
        "pattern": re.compile(r"def \w+\([^)]*\w+(?:\[|: *(?:list|dict|set)\b)[^)]*=\s*(\[\])"),
        "description": "Mutable default arguments are shared across all calls to the function.",
        "suggestion": "Use None as the default and initialize the mutable value inside the function body.",
        "languages": ["python"],
    },
    {
        "id": "SA004",
        "title": "Print statement in production path",
        "severity": "low",
        "category": "maintainability",
        "pattern": re.compile(r"^\s*print\(", re.MULTILINE),
        "description": "Print statements should be replaced with proper logging in production code.",
        "suggestion": "Use logging.getLogger(__name__).info/debug/warning instead of print().",
        "languages": ["python"],
    },
    {
        "id": "SA005",
        "title": "SQL string concatenation / interpolation",
        "severity": "high",
        "category": "bug",
        "pattern": re.compile(r"(?:f\"[^\"]*?\b(?:SELECT|INSERT|UPDATE|DELETE|DROP)\b|f'[^']*?\b(?:SELECT|INSERT|UPDATE|DELETE|DROP)\b)", re.IGNORECASE),
        "description": "SQL query built with f-string interpolation is prone to SQL injection and syntax errors.",
        "suggestion": "Use parameterized queries (SQLAlchemy text() with bindparams, or psycopg2 %s placeholders).",
    },
    {
        "id": "SA006",
        "title": "Broad exception caught",
        "severity": "low",
        "category": "maintainability",
        "pattern": re.compile(r"except Exception\s*(?:as \w+)?:", re.MULTILINE),
        "description": "Catching 'Exception' may hide unexpected errors. Consider a narrower type.",
        "suggestion": "Catch the most specific exception type that you expect.",
    },
    {
        "id": "SA007",
        "title": "Hardcoded absolute path",
        "severity": "low",
        "category": "reliability",
        "pattern": re.compile(r"[\"'](?:/[a-z]+/|C:\\)"),
        "description": "Hardcoded absolute paths make the code non-portable across environments.",
        "suggestion": "Use relative paths, pathlib, or environment variables for paths.",
    },
    {
        "id": "SA008",
        "title": "Open without context manager",
        "severity": "low",
        "category": "reliability",
        "pattern": re.compile(r"(\w+)\s*=\s*open\(", re.MULTILINE),
        "description": "Using open() without 'with' may leak file handles.",
        "suggestion": "Use 'with open(...) as f:' to guarantee the file is closed.",
        "languages": ["python"],
    },
]


def _line_number(text: str, match_start: int) -> int:
    """Derive 1-based line number from character offset."""
    return text[:match_start].count("\n") + 1


def _find_diff_lines(diff_text: str) -> set[int]:
    """Extract the set of added-line numbers from the diff to filter findings to changed lines."""
    changed: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_text, re.MULTILINE):
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) else 1
        for ln in range(start, start + count):
            changed.add(ln)
    return changed


def analyze(diff_text: str, changed_files: list[dict]) -> list[dict]:
    """Run pattern-based static analysis on diff text. Returns list of Finding dicts."""
    if not diff_text:
        return []

    findings: list[dict] = []

    for check in _CHECKS:
        lang_filter = check.get("languages")
        if lang_filter and changed_files:
            file_langs = {f.get("language") for f in changed_files}
            if not file_langs.intersection(lang_filter):
                continue

        for m in check["pattern"].finditer(diff_text):
            linenum = _line_number(diff_text, m.start())

            evidence = diff_text[max(0, m.start() - 20):m.end() + 40].strip().replace("\n", " ")[:200]

            findings.append({
                "agent_name": "static_analysis_agent",
                "severity": check["severity"],
                "category": check["category"],
                "file_path": None,
                "line_number": linenum,
                "title": check["title"],
                "description": check["description"],
                "evidence": evidence,
                "suggestion": check["suggestion"],
                "confidence": 0.75,
            })

    logger.info("Static analysis produced %d finding(s).", len(findings))
    return findings
