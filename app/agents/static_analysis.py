"""Static Analysis Agent — pattern-based code analysis without LLM."""

from __future__ import annotations

import re
import logging
import ast

from app.agents.diff_utils import detect_language, is_code_file, review_text_by_file
from app.agents.evidence_extractor import extract_evidence, line_span_for_match

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

_AST_CHECK_IDS = {"SA001", "SA002", "SA003", "SA004", "SA006", "SA008"}


def _mapped_line(line_numbers: list[int], lineno: int | None) -> int | None:
    if lineno is None:
        return None
    index = lineno - 1
    return line_numbers[index] if 0 <= index < len(line_numbers) else lineno


def _ast_finding(
    check: dict,
    file_path: str,
    text: str,
    line_numbers: list[int],
    lineno: int | None,
    end_lineno: int | None,
    diff_text: str,
    changed_files: list[dict],
) -> dict:
    line_start = _mapped_line(line_numbers, lineno)
    line_end = _mapped_line(line_numbers, end_lineno)
    evidence = extract_evidence(
        diff_text,
        changed_files,
        file_path,
        line_start,
        line_end,
    )
    return {
        "agent_name": "static_analysis_agent",
        "severity": check["severity"],
        "category": check["category"],
        "file_path": file_path,
        "line_number": line_start,
        "line_start": line_start,
        "line_end": line_end,
        "title": check["title"],
        "description": check["description"],
        "evidence": evidence,
        "suggestion": check["suggestion"],
        "confidence": 0.82,
    }


def _is_exception_name(node: ast.AST | None, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_ellipsis_expr(node: ast.AST) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and node.value.value is Ellipsis


def _python_ast_findings(
    file_path: str,
    text: str,
    line_numbers: list[int],
    diff_text: str,
    changed_files: list[dict],
) -> list[dict] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    findings: list[dict] = []
    checks = {check["id"]: check for check in _CHECKS}

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                findings.append(_ast_finding(checks["SA001"], file_path, text, line_numbers, node.lineno, node.end_lineno, diff_text, changed_files))
            elif _is_exception_name(node.type, "Exception"):
                findings.append(_ast_finding(checks["SA006"], file_path, text, line_numbers, node.lineno, node.end_lineno, diff_text, changed_files))
            if node.body and all(isinstance(item, ast.Pass) or _is_ellipsis_expr(item) for item in node.body):
                findings.append(_ast_finding(checks["SA002"], file_path, text, line_numbers, node.lineno, node.end_lineno, diff_text, changed_files))

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [item for item in node.args.kw_defaults if item is not None]
            if any(isinstance(default, (ast.List, ast.Dict, ast.Set)) for default in defaults):
                findings.append(_ast_finding(checks["SA003"], file_path, text, line_numbers, node.lineno, node.end_lineno, diff_text, changed_files))

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "print":
                findings.append(_ast_finding(checks["SA004"], file_path, text, line_numbers, node.lineno, node.end_lineno, diff_text, changed_files))

        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "open":
                findings.append(_ast_finding(checks["SA008"], file_path, text, line_numbers, node.lineno, node.end_lineno, diff_text, changed_files))

    return findings


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
    findings: list[dict] = []
    review_text = review_text_by_file(diff_text, changed_files)
    if not review_text:
        return findings
    languages_by_file = {
        f.get("file_path"): f.get("language")
        for f in changed_files
        if f.get("file_path")
    }
    ast_parsed_files: set[str] = set()
    for file_path, (added_text, line_numbers) in review_text.items():
        language = languages_by_file.get(file_path) or detect_language(file_path)
        if language != "python" or not is_code_file(file_path, language):
            continue
        ast_findings = _python_ast_findings(file_path, added_text, line_numbers, diff_text, changed_files)
        if ast_findings is None:
            continue
        ast_parsed_files.add(file_path)
        findings.extend(ast_findings)

    for check in _CHECKS:
        lang_filter = check.get("languages")

        for file_path, (added_text, line_numbers) in review_text.items():
            language = languages_by_file.get(file_path) or detect_language(file_path)
            if not is_code_file(file_path, language):
                continue
            if lang_filter and language not in lang_filter:
                continue
            if file_path in ast_parsed_files and check.get("id") in _AST_CHECK_IDS:
                continue
            for m in check["pattern"].finditer(added_text):
                line_start, line_end = line_span_for_match(line_numbers, added_text, m.start(), m.end())
                evidence = extract_evidence(diff_text, changed_files, file_path, line_start, line_end)

                findings.append({
                    "agent_name": "static_analysis_agent",
                    "severity": check["severity"],
                    "category": check["category"],
                    "file_path": file_path,
                    "line_number": line_start,
                    "line_start": line_start,
                    "line_end": line_end,
                    "title": check["title"],
                    "description": check["description"],
                    "evidence": evidence,
                    "suggestion": check["suggestion"],
                    "confidence": 0.75,
                })

    logger.info("Static analysis produced %d finding(s).", len(findings))
    return findings
