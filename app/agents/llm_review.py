"""LLM Review Agent — deep logic/architecture review (mock LLM for P1)."""

from __future__ import annotations

import logging
import json
import re

from app.config import settings
from app.agents.diff_utils import added_text_by_file, is_code_file
from app.agents.evidence_extractor import extract_evidence
from app.services.llm_client import call_llm
from app.services.llm_safety import external_llm_enabled, llm_mode, redact_text

logger = logging.getLogger(__name__)

LLM_REVIEW_SYSTEM_PROMPT = """You are the LLM Review Agent in a multi-agent code review system.
Return only JSON with this shape: {"findings": [Finding]}.
Each Finding must include agent_name, severity, category, file_path, line_number, title,
description, evidence, suggestion, confidence. Only report actionable defects supported by
specific changed code. Do not report generic reminders such as "needs review" or broad
best-practice advice. If a finding lacks file_path, line_number, evidence, and a concrete
fix suggestion, omit it."""


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
                    "evidence": extract_evidence(diff_text, changed_files, file_path, line_number, line_number),
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
                    "evidence": extract_evidence("", changed_files, file_path, line_number, line_number),
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
    """Simulate LLM review findings for concrete, evidence-backed risks only."""
    findings: list[dict] = []
    seen_signatures: set[tuple[str, str, int]] = set()

    def add_finding(change: dict, severity: str, category: str, title: str,
                    description: str, suggestion: str, confidence: float,
                    attack_scenario: str = "") -> None:
        signature = (title, change["file_path"], change["line_number"])
        if signature in seen_signatures:
            return
        seen_signatures.add(signature)
        findings.append({
            "agent_name": "llm_review_agent",
            "severity": severity,
            "category": category,
            "file_path": change["file_path"],
            "line_number": change["line_number"],
            "title": title,
            "description": description,
            "evidence": change.get("evidence") or change["text"],
            "suggestion": suggestion,
            "confidence": confidence,
            "attack_scenario": attack_scenario,
        })

    for change in changes:
        line = change["text"]
        lowered = line.lower()

        if (
            re.search(r"\bf[\"'][^\"']*\b(select|insert|update|delete|drop|alter|create)\b", line, re.IGNORECASE)
            and "{" in line
        ):
            add_finding(
                change,
                "critical",
                "security",
                "Potential SQL injection via f-string",
                "SQL query text is built with f-string interpolation.",
                "Use parameterized queries or an ORM instead of interpolating values into SQL.",
                0.86,
                "User-controlled values can alter the SQL statement when interpolated into the query string.",
            )
        elif "shell=true" in lowered.replace(" ", "") or re.search(r"\bos\.system\s*\(", line):
            add_finding(
                change,
                "critical",
                "security",
                "Potential command injection",
                "Shell command execution is enabled in changed code.",
                "Avoid shell=True/os.system; pass argument lists to subprocess and validate user input.",
                0.84,
                "User-controlled shell metacharacters can execute unintended commands.",
            )
        elif re.search(r"\b(eval|exec|compile)\s*\(", line):
            add_finding(
                change,
                "critical",
                "security",
                "Use of dangerous eval/exec",
                "Changed code executes dynamic Python code.",
                "Remove eval/exec/compile or replace it with an explicit dispatch table.",
                0.84,
                "If user-controlled input reaches this call, an attacker can execute arbitrary code.",
            )

    logger.info("Mock LLM review produced %d finding(s).", len(findings))
    return findings


def review(diff_text: str, changed_files: list[dict],
           aggregated_findings: list[dict], project_context: dict) -> list[dict]:
    """Run LLM deep review (mock in P1). Returns list of Finding dicts."""
    changes = _reviewable_changes(diff_text, changed_files)
    review_text, file_paths = _reviewable_text(changes)
    if not review_text.strip():
        return []

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
