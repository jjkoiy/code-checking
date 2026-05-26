"""Finding Aggregator Agent — dedup, normalize severity, mark blocking issues."""

from __future__ import annotations

import logging
import re
import uuid
from difflib import SequenceMatcher

from app.models.findings import normalize_findings

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _compact_text(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"[^a-z0-9_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _finding_text(finding: dict) -> str:
    return " ".join(
        _compact_text(finding.get(field))
        for field in (
            "title",
            "description",
            "suggestion",
            "attack_scenario",
            "evidence",
        )
    )


def _risk_signature(finding: dict) -> str:
    text = _finding_text(finding)
    if finding.get("rule_family"):
        return str(finding["rule_family"])
    if "sql" in text and any(term in text for term in ("injection", "f string", "interpolation", "parameterized", "query")):
        return "sql-injection"
    if any(term in text for term in ("shell true", "os system", "subprocess", "command injection")):
        return "command-injection"
    if any(term in text for term in ("password", "secret", "credential", "api_key", "apikey", "token", "private_key")):
        return "hardcoded-secret"
    if any(term in text for term in ("eval", "exec", "compile")):
        return "dangerous-code-execution"
    if any(term in text for term in ("pickle", "yaml load", "marshal", "deserialization")):
        return "insecure-deserialization"
    if any(term in text for term in ("md5", "sha1", "weak hash")):
        return "weak-hash"
    if any(term in text for term in ("bare except", "empty except", "except exception", "broad exception", "silently swallows", "narrower type")):
        return "exception-handling"
    if "http" in text and "https" in text:
        return "plain-http"
    if "debug mode" in text:
        return "debug-mode"
    if "mutable default" in text:
        return "mutable-default"
    if "print" in text:
        return "print-statement"
    if "open" in text and any(term in text for term in ("context manager", "file handle")):
        return "open-without-context-manager"
    if any(term in text for term in ("todo", "fixme", "hack")) and any(term in text for term in ("auth", "permission", "role", "token", "security")):
        return "auth-todo"
    if any(term in text for term in ("todo", "fixme", "hack")):
        return "todo-comment"
    return ""


def _line_span(finding: dict) -> tuple[int | None, int | None]:
    start = finding.get("line_start") or finding.get("line_number")
    end = finding.get("line_end") or start
    return start, end


def _near_location(a: dict, b: dict, tolerance: int = 2) -> bool:
    if a.get("file_path") != b.get("file_path"):
        return False
    a_start, a_end = _line_span(a)
    b_start, b_end = _line_span(b)
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return True
    return not (a_end + tolerance < b_start or b_end + tolerance < a_start)


def _same_evidence(a: dict, b: dict) -> bool:
    a_evidence = _compact_text(a.get("evidence"))
    b_evidence = _compact_text(b.get("evidence"))
    if not a_evidence or not b_evidence:
        return False
    return a_evidence == b_evidence or _text_similarity(a_evidence, b_evidence) > 0.90


def _is_duplicate_finding(finding: dict, existing: dict) -> bool:
    if finding.get("file_path") != existing.get("file_path"):
        return False

    same_category = finding.get("category") == existing.get("category")
    same_location = _near_location(finding, existing, tolerance=0)
    near_location = _near_location(finding, existing, tolerance=2)
    same_evidence = _same_evidence(finding, existing)
    title_similarity = _text_similarity(
        finding.get("title", ""), existing.get("title", "")
    )
    description_similarity = _text_similarity(
        finding.get("description", ""), existing.get("description", "")
    )
    finding_signature = _risk_signature(finding)
    existing_signature = _risk_signature(existing)

    if near_location and finding_signature and finding_signature == existing_signature:
        return True
    if same_location and same_category and (title_similarity > 0.80 or description_similarity > 0.80):
        return True
    if same_location and same_evidence and (same_category or title_similarity > 0.55 or description_similarity > 0.55):
        return True
    return False


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0) else b


def _finding_rank(finding: dict) -> tuple[int, float]:
    return (
        _SEVERITY_ORDER.get(finding.get("severity", "low"), 0),
        float(finding.get("confidence", 0) or 0),
    )


def _normalize_severity(finding: dict) -> str:
    category = finding.get("category", "")
    confidence = finding.get("confidence", 0.5)
    severity = finding.get("severity", "low")

    if confidence < 0.4:
        return "low"

    if category == "security" and severity in ("high", "critical"):
        if confidence >= 0.75:
            return severity
        return "medium"

    if category in ("bug", "logic", "reliability"):
        if confidence >= 0.8 and severity == "high":
            return "high"

    if category == "style":
        return "low" if severity == "medium" else severity

    return severity


def _certainty(finding: dict) -> str:
    confidence = float(finding.get("confidence", 0) or 0)
    if confidence >= 0.8:
        return "confirmed"
    if confidence >= 0.6:
        return "potential"
    return "needs_context"


def _is_actionable_finding(finding: dict, validation_warnings: list[dict] | None) -> bool:
    missing_fields = [
        field
        for field in ("file_path", "line_number", "evidence", "suggestion")
        if finding.get(field) in (None, "", [])
    ]
    is_llm_finding = finding.get("agent_name") == "llm_review_agent"
    if is_llm_finding and missing_fields:
        if validation_warnings is not None:
            validation_warnings.append({
                "agent": finding.get("agent_name", "unknown"),
                "title": finding.get("title", ""),
                "error": "dropped non-actionable LLM finding missing " + ", ".join(missing_fields),
            })
        return False

    title = _compact_text(finding.get("title"))
    confidence = float(finding.get("confidence", 0) or 0)
    if is_llm_finding and "needs targeted review" in title and confidence < 0.7:
        if validation_warnings is not None:
            validation_warnings.append({
                "agent": finding.get("agent_name", "unknown"),
                "title": finding.get("title", ""),
                "error": "dropped generic low-confidence review reminder",
            })
        return False

    return True


def _is_blocking(finding: dict) -> bool:
    severity = finding.get("severity", "low")
    category = finding.get("category", "")
    confidence = finding.get("confidence", 0.0)

    if severity == "critical":
        return True
    if severity == "high" and category == "security":
        return True
    if severity == "high" and category in ("bug", "logic", "reliability"):
        return confidence >= 0.8
    return False


def _merge_text(existing: str, incoming: str) -> str:
    existing = (existing or "").strip()
    incoming = (incoming or "").strip()
    if not incoming:
        return existing
    if not existing:
        return incoming
    if _compact_text(incoming) in _compact_text(existing):
        return existing
    return f"{existing} {incoming}"


def _apply_family_merge(finding: dict) -> None:
    family = finding.get("rule_family") or _risk_signature(finding)
    if family:
        finding["rule_family"] = family
    if family == "exception-handling":
        text = _finding_text(finding)
        has_broad = "broad exception" in text or "except exception" in text
        has_empty = "empty except" in text or "silently swallows" in text or "pass" in _compact_text(finding.get("evidence"))
        if has_broad and has_empty:
            finding["title"] = "Overly broad exception catch with empty handling"
            finding["description"] = (
                "The changed code catches a broad exception type and then silently ignores it, "
                "which can hide real failures and make recovery behavior unclear."
            )
            finding["suggestion"] = (
                "Catch the specific expected exception, log useful context, and either handle the error explicitly or re-raise it."
            )
            finding["severity"] = _max_severity(finding.get("severity", "low"), "medium")
    elif family == "sql-injection":
        finding["category"] = "security"
        finding["severity"] = _max_severity(finding.get("severity", "low"), "critical")
        finding["suggestion"] = _merge_text(
            finding.get("suggestion", ""),
            "Add a regression test with SQL injection payloads and verify the query uses bound parameters.",
        )
    elif family == "auth-todo":
        finding["category"] = "security"
        finding["severity"] = _max_severity(finding.get("severity", "low"), "medium")


def aggregate(
    findings: list[dict],
    validation_warnings: list[dict] | None = None,
) -> list[dict]:
    """Dedup findings by file+category+similarity, normalize severity, mark blocking."""
    if not findings:
        return []

    findings = normalize_findings(findings, validation_warnings=validation_warnings)
    findings = [
        finding
        for finding in findings
        if _is_actionable_finding(finding, validation_warnings)
    ]
    if not findings:
        return []

    for finding in findings:
        finding["severity"] = _normalize_severity(finding)
        finding["blocking"] = _is_blocking(finding)
        finding["rule_family"] = finding.get("rule_family") or _risk_signature(finding)
        finding["certainty"] = finding.get("certainty") or _certainty(finding)

    deduped: list[dict] = []
    for finding in findings:
        duplicate = None
        for existing in deduped:
            if _is_duplicate_finding(finding, existing):
                duplicate = existing
                break

        if duplicate:
            sources: list[str] = duplicate.setdefault("source_agents", [])
            for agent_name in finding.get("source_agents") or [finding.get("agent_name", "unknown")]:
                if agent_name not in sources:
                    sources.append(agent_name)
            should_replace_display = _finding_rank(finding) > _finding_rank(duplicate)
            duplicate["confidence"] = max(
                duplicate.get("confidence", 0), finding.get("confidence", 0)
            )
            duplicate["severity"] = _max_severity(
                duplicate.get("severity", "low"), finding.get("severity", "low")
            )
            duplicate["suggestion"] = _merge_text(
                duplicate.get("suggestion", ""), finding.get("suggestion", "")
            )
            duplicate["description"] = _merge_text(
                duplicate.get("description", ""), finding.get("description", "")
            )
            if len(str(finding.get("evidence", ""))) > len(str(duplicate.get("evidence", ""))):
                duplicate["evidence"] = finding["evidence"]
                duplicate["line_start"] = finding.get("line_start") or finding.get("line_number")
                duplicate["line_end"] = finding.get("line_end") or finding.get("line_number")
            if should_replace_display:
                preserved = {
                    "id": duplicate.get("id"),
                    "source_agents": sources,
                    "confidence": duplicate["confidence"],
                    "severity": duplicate["severity"],
                    "suggestion": duplicate["suggestion"],
                    "description": duplicate["description"],
                    "evidence": duplicate.get("evidence", ""),
                    "line_start": duplicate.get("line_start"),
                    "line_end": duplicate.get("line_end"),
                    "rule_family": duplicate.get("rule_family") or finding.get("rule_family"),
                }
                duplicate.update({
                    key: value
                    for key, value in finding.items()
                    if value not in (None, "", [])
                })
                duplicate.update(preserved)
        else:
            finding["id"] = uuid.uuid4().hex[:10]
            finding["source_agents"] = finding.get("source_agents") or [
                finding.get("agent_name", "unknown")
            ]
            finding["rule_family"] = finding.get("rule_family") or _risk_signature(finding)
            deduped.append(finding)

    # Re-apply normalize + blocking after merges
    for f in deduped:
        _apply_family_merge(f)
        f["severity"] = _normalize_severity(f)
        f["blocking"] = _is_blocking(f)
        f["certainty"] = f.get("certainty") or _certainty(f)

    # Sort: blocking first, then critical > high > medium > low, then by confidence desc
    def _sort_key(f: dict) -> tuple:
        return (
            not f.get("blocking", False),
            -_SEVERITY_ORDER.get(f.get("severity", "low"), 0),
            -f.get("confidence", 0),
        )

    deduped.sort(key=_sort_key)

    logger.info("Aggregated %d findings → %d after dedup.", len(findings), len(deduped))
    return deduped
