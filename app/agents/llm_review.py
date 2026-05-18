"""LLM Review Agent — deep logic/architecture review (mock LLM for P1)."""

from __future__ import annotations

import logging
import json

from app.config import settings
from app.agents.diff_utils import added_text_by_file, is_code_file
from app.services.llm_client import call_llm
from app.services.llm_safety import external_llm_enabled, llm_mode, redact_text

logger = logging.getLogger(__name__)

LLM_REVIEW_SYSTEM_PROMPT = """You are the LLM Review Agent in a multi-agent code review system.
Return only JSON with this shape: {"findings": [Finding]}.
Each Finding must include agent_name, severity, category, file_path, line_number, title,
description, evidence, suggestion, confidence. Only report issues supported by the diff."""


def _reviewable_changes(diff_text: str, changed_files: list[dict]) -> list[dict]:
    """Collect actual changed code lines for heuristic review."""
    languages_by_file = {
        f.get("file_path"): f.get("language")
        for f in changed_files
        if f.get("file_path")
    }
    changes: list[dict] = []

    fallback_file_path = next(
        (f.get("file_path") for f in changed_files if f.get("file_path")),
        None,
    )
    for file_path, (added_text, line_numbers) in added_text_by_file(
        diff_text,
        fallback_file_path=fallback_file_path,
        allow_raw=True,
    ).items():
        if is_code_file(file_path, languages_by_file.get(file_path)):
            for line_number, line_text in zip(line_numbers, added_text.splitlines()):
                changes.append({
                    "file_path": file_path,
                    "line_number": line_number,
                    "text": line_text,
                })

    for changed in changed_files:
        file_path = changed.get("file_path")
        content = changed.get("content")
        if not content or not is_code_file(file_path, changed.get("language")):
            continue
        if not any(item["file_path"] == file_path for item in changes):
            for line_number, line_text in enumerate(content.splitlines(), start=1):
                changes.append({
                    "file_path": file_path,
                    "line_number": line_number,
                    "text": line_text,
                })

    return changes


def _reviewable_text(changes: list[dict]) -> tuple[str, list[str]]:
    file_paths = sorted({item["file_path"] for item in changes if item.get("file_path")})
    snippets: list[str] = []
    for file_path in file_paths:
        lines = [
            f"{item['line_number']}: {item['text']}"
            for item in changes
            if item.get("file_path") == file_path
        ]
        snippets.append(f"File: {file_path}\n" + "\n".join(lines))
    return "\n\n".join(snippets), file_paths


def _mock_llm_call(changes: list[dict]) -> list[dict]:
    """Simulate LLM review findings based on input heuristics.
    In production this will be replaced with a real LLM API call via app.config.llm_provider/model.
    """
    findings: list[dict] = []
    seen_categories: set[str] = set()

    def add_finding(change: dict, severity: str, category: str, title: str,
                    description: str, suggestion: str, confidence: float) -> None:
        if category in seen_categories:
            return
        seen_categories.add(category)
        findings.append({
            "agent_name": "llm_review_agent",
            "severity": severity,
            "category": category,
            "file_path": change["file_path"],
            "line_number": change["line_number"],
            "title": title,
            "description": description,
            "evidence": change["text"].strip(),
            "suggestion": suggestion,
            "confidence": confidence,
        })

    rules = [
        (
            "logic",
            ["auth", "login", "logout", "permission", "role", "access control"],
            "medium",
            "Authentication-related change needs targeted review",
            "This changed line touches authentication or authorization behavior.",
            "Verify this specific path enforces the intended auth and role checks before business logic runs.",
            0.58,
        ),
        (
            "reliability",
            ["except", "error", "raise", "try", "catch", "fallback"],
            "low",
            "Error handling path needs targeted review",
            "This changed line affects exception or fallback behavior.",
            "Confirm the error is handled at the right boundary and returns an actionable, non-leaky response.",
            0.48,
        ),
        (
            "data",
            ["sql", "query", "database", "db", "session", "commit", "rollback", "transaction"],
            "medium",
            "Database interaction needs targeted review",
            "This changed line touches database or transaction behavior.",
            "Check transaction boundaries, rollback behavior, and whether user-controlled values are safely parameterized.",
            0.52,
        ),
        (
            "compatibility",
            ["api", "endpoint", "router", "route", "request", "response", "status_code"],
            "medium",
            "API surface change needs targeted review",
            "This changed line appears to affect the API contract.",
            "Verify request and response compatibility, including status codes and schema changes.",
            0.50,
        ),
        (
            "validation",
            ["input", "user", "body", "param", "json", "form", "query_param"],
            "low",
            "Input handling needs targeted validation review",
            "This changed line handles user-controlled input.",
            "Add or verify validators for empty, malformed, oversized, and unexpected inputs.",
            0.48,
        ),
    ]

    for change in changes:
        line = change["text"].lower()
        for category, keywords, severity, title, description, suggestion, confidence in rules:
            if category not in seen_categories and any(kw in line for kw in keywords):
                add_finding(change, severity, category, title, description, suggestion, confidence)

    logger.info("Mock LLM review produced %d finding(s).", len(findings))
    return findings


def review(diff_text: str, changed_files: list[dict],
           aggregated_findings: list[dict], project_context: dict) -> list[dict]:
    """Run LLM deep review (mock in P1). Returns list of Finding dicts."""
    changes = _reviewable_changes(diff_text, changed_files)
    review_text, file_paths = _reviewable_text(changes)
    if not review_text.strip():
        return []

    # Build a prompt that summarizes what we're reviewing (used by mock heuristics)
    combined_context = (
        f"Files: {' '.join(file_paths)}. "
        f"Languages: {project_context.get('languages', [])}. "
        f"Changed code length: {len(review_text)} chars."
    )

    user_prompt = json.dumps({
        "changed_code": review_text[: settings.review_max_diff_chars],
        "changed_files": [
            f for f in changed_files
            if is_code_file(f.get("file_path"), f.get("language"))
        ],
        "aggregated_findings": aggregated_findings,
    })

    mode = llm_mode()
    if not external_llm_enabled():
        logger.info("LLM review running in %s mode.", mode)
        return _mock_llm_call(changes)

    try:
        response = call_llm(
            model=settings.llm_model,
            system_prompt=LLM_REVIEW_SYSTEM_PROMPT,
            user_prompt=redact_text(user_prompt),
            response_format="json",
        )
        parsed = response.get("parsed_json")
        if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
            logger.info("LLM review produced %d finding(s).", len(parsed["findings"]))
            return parsed["findings"]
        if isinstance(parsed, list):
            logger.info("LLM review produced %d finding(s).", len(parsed))
            return parsed
    except Exception as e:
        logger.warning("LLM review fell back to mock heuristics: %s", e)

    findings = _mock_llm_call(changes)

    return findings
