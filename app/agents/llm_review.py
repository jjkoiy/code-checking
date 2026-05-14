"""LLM Review Agent — deep logic/architecture review (mock LLM for P1)."""

from __future__ import annotations

import logging
import uuid

from app.config import settings

logger = logging.getLogger(__name__)


def _mock_llm_call(system_prompt: str, user_prompt: str) -> list[dict]:
    """Simulate LLM review findings based on input heuristics.
    In production this will be replaced with a real LLM API call via app.config.llm_provider/model.
    """
    combined = (user_prompt + " " + system_prompt).lower()
    findings: list[dict] = []

    logic_keywords = ["auth", "login", "logout", "permission", "role", "access control"]
    if any(kw in combined for kw in logic_keywords):
        findings.append({
            "agent_name": "llm_review_agent",
            "severity": "medium",
            "category": "logic",
            "file_path": None,
            "line_number": None,
            "title": "Authentication flow may need review",
            "description": "Changes touch authentication-related code. Verify that auth checks are applied consistently across all affected endpoints.",
            "evidence": "Auth-related keywords detected in changed files.",
            "suggestion": "Ensure every protected endpoint has an auth dependency and that role checks are applied before business logic.",
            "confidence": 0.55,
        })

    error_keywords = ["except", "error", "raise", "try", "catch", "fallback"]
    if any(kw in combined for kw in error_keywords):
        findings.append({
            "agent_name": "llm_review_agent",
            "severity": "low",
            "category": "reliability",
            "file_path": None,
            "line_number": None,
            "title": "Error handling should be reviewed for completeness",
            "description": "Error handling patterns detected. Verify that exceptions are translated appropriately at API boundaries and that users get actionable error messages.",
            "evidence": "Exception/error handling keywords found in diff.",
            "suggestion": "Map internal exceptions to appropriate HTTP status codes. Avoid leaking stack traces to API consumers.",
            "confidence": 0.45,
        })

    db_keywords = ["sql", "query", "database", "db", "session", "commit", "rollback", "transaction"]
    if any(kw in combined for kw in db_keywords):
        findings.append({
            "agent_name": "llm_review_agent",
            "severity": "medium",
            "category": "reliability",
            "file_path": None,
            "line_number": None,
            "title": "Database session/transaction management should be verified",
            "description": "Database operations detected. Verify that sessions are properly closed and transactions are committed or rolled back on error.",
            "evidence": "Database-related keywords found in diff.",
            "suggestion": "Use context managers for DB sessions. Ensure rollback on exceptions and commit only on success.",
            "confidence": 0.50,
        })

    api_keywords = ["api", "endpoint", "router", "route", "request", "response", "status_code"]
    if any(kw in combined for kw in api_keywords):
        findings.append({
            "agent_name": "llm_review_agent",
            "severity": "medium",
            "category": "compatibility",
            "file_path": None,
            "line_number": None,
            "title": "API compatibility should be checked",
            "description": "Changes affect API surface. Verify backward compatibility and that request/response schemas haven't broken existing consumers.",
            "evidence": "API-related keywords detected in changed files.",
            "suggestion": "Review all changed endpoints for backward compatibility. Consider API versioning if breaking changes are intentional.",
            "confidence": 0.50,
        })

    input_keywords = ["input", "user", "body", "param", "json", "form", "query_param"]
    if any(kw in combined for kw in input_keywords):
        findings.append({
            "agent_name": "llm_review_agent",
            "severity": "low",
            "category": "reliability",
            "file_path": None,
            "line_number": None,
            "title": "Input validation should be comprehensive",
            "description": "User input handling detected. Verify that all inputs are validated with appropriate Pydantic models or manual checks.",
            "evidence": "Input-handling keywords found in diff.",
            "suggestion": "Add Pydantic validators for business rules. Check for edge cases: empty strings, oversized inputs, unexpected types.",
            "confidence": 0.45,
        })

    logger.info("Mock LLM review produced %d finding(s).", len(findings))
    return findings


def review(diff_text: str, changed_files: list[dict],
           aggregated_findings: list[dict], project_context: dict) -> list[dict]:
    """Run LLM deep review (mock in P1). Returns list of Finding dicts."""
    if not diff_text and not changed_files:
        return []

    # Build a prompt that summarizes what we're reviewing (used by mock heuristics)
    file_paths = [f.get("file_path", "") for f in changed_files]
    combined_context = (
        f"Files: {' '.join(file_paths)}. "
        f"Languages: {project_context.get('languages', [])}. "
        f"Risk hints: {project_context.get('risk_hints', [])}. "
        f"Diff length: {len(diff_text)} chars."
    )

    logger.info("LLM Review Agent: mock mode (provider=%s, model=%s)", settings.llm_provider, settings.llm_model)

    # TODO P2: Replace with real LLM call:
    #   response = call_llm(
    #       model=settings.llm_model,
    #       system_prompt=LLM_REVIEW_SYSTEM_PROMPT,
    #       user_prompt=combined_context,
    #       response_format="json",
    #   )
    #   return response.parsed_json

    findings = _mock_llm_call(
        system_prompt="",
        user_prompt=" ".join(file_paths) + " " + combined_context,
    )

    return findings
