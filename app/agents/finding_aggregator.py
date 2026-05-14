"""Finding Aggregator Agent — dedup, normalize severity, mark blocking issues."""

from __future__ import annotations

import logging
import uuid
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0) else b


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


def aggregate(findings: list[dict]) -> list[dict]:
    """Dedup findings by file+category+similarity, normalize severity, mark blocking."""
    if not findings:
        return []

    deduped: list[dict] = []
    for finding in findings:
        duplicate = None
        for existing in deduped:
            same_file = finding.get("file_path") == existing.get("file_path")
            same_category = finding.get("category") == existing.get("category")
            same_title = finding.get("title") == existing.get("title")
            similar_title = _text_similarity(
                finding.get("title", ""), existing.get("title", "")
            ) > 0.80

            if same_file and same_category and (same_title or similar_title):
                duplicate = existing
                break

        if duplicate:
            sources: list[str] = duplicate.setdefault("source_agents", [])
            agent_name = finding.get("agent_name", "")
            if agent_name not in sources:
                sources.append(agent_name)
            duplicate["confidence"] = max(
                duplicate.get("confidence", 0), finding.get("confidence", 0)
            )
            duplicate["severity"] = _max_severity(
                duplicate.get("severity", "low"), finding.get("severity", "low")
            )
        else:
            finding["id"] = uuid.uuid4().hex[:10]
            finding["source_agents"] = [finding.get("agent_name", "unknown")]
            finding["severity"] = _normalize_severity(finding)
            finding["blocking"] = _is_blocking(finding)
            deduped.append(finding)

    # Re-apply normalize + blocking after merges
    for f in deduped:
        f["severity"] = _normalize_severity(f)
        f["blocking"] = _is_blocking(f)

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
