"""RAG risk review agent for evidence-backed, knowledge-driven findings."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.diff_utils import detect_language, is_code_file, review_text_by_file
from app.agents.evidence_extractor import extract_evidence
from app.config import settings
from app.services.vector_store import vector_search

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 8
_MAX_EVIDENCE_LINES = 12


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _csv_or_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return [item.lower() for item in _as_list(value)]


def _parse_rule(document: dict[str, Any]) -> dict[str, Any] | None:
    content = document.get("content")
    metadata = document.get("metadata") or {}
    parsed: dict[str, Any] = {}
    if isinstance(content, str) and content.strip():
        try:
            value = json.loads(content)
            if isinstance(value, dict):
                parsed.update(value)
        except json.JSONDecodeError:
            parsed["title"] = content.strip()

    parsed.update({key: value for key, value in metadata.items() if key not in parsed})
    risk_id = str(parsed.get("risk_id") or parsed.get("rule_family") or document.get("id") or "").strip()
    title = str(parsed.get("title") or "").strip()
    suggestion = str(parsed.get("suggestion") or "").strip()
    if not risk_id or not title or not suggestion:
        return None
    parsed["risk_id"] = risk_id
    parsed["rule_id"] = str(document.get("id") or risk_id)
    parsed["title"] = title
    parsed["severity"] = str(parsed.get("severity") or "medium").strip().lower()
    parsed["category"] = str(parsed.get("category") or "security").strip().lower()
    return parsed


def _matches_pattern(text: str, pattern: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern.startswith("regex:"):
        try:
            return bool(re.search(pattern[6:], text, flags=re.IGNORECASE))
        except re.error:
            return False
    return pattern.lower() in text.lower()


def _matching_lines(lines: list[tuple[int, str]], patterns: list[str]) -> list[tuple[int, str]]:
    if not patterns:
        return []
    return [
        (line_number, text)
        for line_number, text in lines
        if any(_matches_pattern(text, pattern) for pattern in patterns)
    ]


def _rule_applies_to_language(rule: dict[str, Any], language: str | None) -> bool:
    languages = _csv_or_list(rule.get("languages"))
    if not languages or not language:
        return True
    return language.lower() in languages


def _context_documents(project_context: dict | None) -> list[dict[str, Any]]:
    if not isinstance(project_context, dict):
        return []
    documents = project_context.get("relevant_project_context")
    return [item for item in documents if isinstance(item, dict)] if isinstance(documents, list) else []


def _context_ids_for_text(project_context: dict | None, text: str) -> list[str]:
    lowered = text.lower()
    context_ids: list[str] = []
    for document in _context_documents(project_context):
        metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
        symbol = str(metadata.get("symbol_name", "")).lower()
        if symbol and symbol in lowered:
            context_ids.append(str(document.get("id")))
    return [item for item in context_ids if item]


def _nearby_pair(
    sources: list[tuple[int, str]],
    sinks: list[tuple[int, str]],
    max_distance: int = 8,
) -> tuple[tuple[int, str], tuple[int, str]] | None:
    if not sources or not sinks:
        return None
    best: tuple[tuple[int, str], tuple[int, str]] | None = None
    best_score: tuple[int, int, int] | None = None
    for source in sources:
        for sink in sinks:
            distance = abs(source[0] - sink[0])
            if distance > max_distance:
                continue
            has_prior_source = any(
                other_source[0] < sink[0]
                and sink[0] - other_source[0] <= max_distance
                for other_source in sources
            )
            source_after_sink_penalty = 1 if source[0] > sink[0] else 0
            same_line_penalty = 1 if source[0] == sink[0] and has_prior_source else 0
            score = (source_after_sink_penalty, same_line_penalty, distance)
            if best_score is None or score < best_score:
                best = (source, sink)
                best_score = score
    return best


def _has_safety_signal(
    rule_family: str,
    text: str,
    sanitizer_patterns: list[str] | None = None,
    project_context: dict | None = None,
) -> bool:
    lowered = text.lower()
    for pattern in sanitizer_patterns or []:
        if _matches_pattern(text, pattern):
            return True
    if rule_family == "path-traversal":
        local_safe = any(
            token in lowered
            for token in ("safe_join", "secure_filename", "is_relative_to", "resolve()")
        )
        if local_safe:
            return True
        return any(
            str(document.get("content", "")).lower().find("safe_join") >= 0
            and "safe_join" in lowered
            for document in _context_documents(project_context)
        )
    if rule_family == "weak-auth-request-param":
        return "current_user" in lowered and not any(
            token in lowered for token in ("request.args", "request.form", "request.json")
        )
    if rule_family == "client-controlled-payment-amount":
        return any(
            token in lowered
            for token in ("order.total", "order.amount", "total_amount", "load_order")
        ) and "request.json" not in lowered
    return False


def _line_window(start: int, end: int) -> tuple[int, int]:
    if end < start:
        end = start
    if end - start + 1 <= _MAX_EVIDENCE_LINES:
        return start, end
    return start, start + _MAX_EVIDENCE_LINES - 1


def _fallback_evidence(lines: list[tuple[int, str]], start: int, end: int) -> str:
    return "\n".join(text for line_number, text in lines if start <= line_number <= end)


def _finding_for_rule(
    rule: dict[str, Any],
    file_path: str,
    lines: list[tuple[int, str]],
    full_text: str,
    diff_text: str,
    changed_files: list[dict],
    project_context: dict | None = None,
) -> dict[str, Any] | None:
    rule_family = str(rule.get("risk_id") or "").strip()
    sanitizer_patterns = _as_list(rule.get("sanitizer_patterns"))

    source_patterns = _as_list(rule.get("source_patterns"))
    sink_patterns = _as_list(rule.get("sink_patterns"))
    source_hits = _matching_lines(lines, source_patterns)
    sink_hits = _matching_lines(lines, sink_patterns)

    if source_patterns and sink_patterns:
        pair = _nearby_pair(source_hits, sink_hits)
        if pair is None:
            return None
        source, sink = pair
        related_sink_lines = [
            line_number
            for line_number, _text in sink_hits
            if abs(source[0] - line_number) <= 8
        ]
        line_start, line_end = _line_window(
            min([source[0], sink[0], *related_sink_lines]),
            max([source[0], sink[0], *related_sink_lines]),
        )
        line_number = sink[0]
    elif sink_patterns:
        if not sink_hits:
            return None
        sink = sink_hits[0]
        line_start, line_end = sink[0], sink[0]
        line_number = sink[0]
    else:
        return None

    evidence = extract_evidence(diff_text, changed_files, file_path, line_start, line_end)
    if not evidence:
        evidence = _fallback_evidence(lines, line_start, line_end)
    if not evidence.strip():
        return None
    if _has_safety_signal(rule_family, evidence, sanitizer_patterns, project_context):
        return None

    description = str(rule.get("evidence_requirements") or rule.get("description") or rule["title"])
    attack_scenario = str(rule.get("attack_scenario") or "")
    context_ids = _context_ids_for_text(project_context, full_text + "\n" + evidence)
    confidence = 0.84 if source_patterns and sink_patterns else 0.72
    return {
        "agent_name": "rag_risk_review_agent",
        "severity": rule.get("severity", "medium"),
        "category": rule.get("category", "security"),
        "file_path": file_path,
        "line_number": line_number,
        "line_start": line_start,
        "line_end": line_end,
        "title": rule["title"],
        "description": description,
        "evidence": evidence,
        "suggestion": rule["suggestion"],
        "attack_scenario": attack_scenario,
        "confidence": confidence,
        "rule_family": rule_family,
        "rule_id": str(rule.get("rule_id") or rule_family),
        "context_ids": context_ids,
    }


def review(diff_text: str, changed_files: list[dict], project_context: dict | None = None) -> list[dict]:
    """Retrieve risk cards and emit only findings supported by changed-code evidence."""
    findings: list[dict] = []
    review_text = review_text_by_file(diff_text, changed_files)
    if not review_text:
        return findings

    languages_by_file = {
        f.get("file_path"): f.get("language")
        for f in changed_files
        if f.get("file_path")
    }
    seen: set[tuple[str, str, int]] = set()

    for file_path, (added_text, line_numbers) in review_text.items():
        language = languages_by_file.get(file_path) or detect_language(file_path)
        if not is_code_file(file_path, language):
            continue
        query = "\n".join([
            f"file:{file_path}",
            f"language:{language or 'unknown'}",
            added_text[:4000],
        ])
        try:
            top_k = max(1, int(settings.rag_vector_top_k or _DEFAULT_TOP_K))
            retrieved = vector_search("risk_rules", query, top_k=top_k).get("documents", [])
        except Exception as exc:
            logger.warning("RAG risk rule lookup skipped: %s", exc)
            continue

        lines = list(zip(line_numbers, added_text.splitlines()))
        for document in retrieved:
            rule = _parse_rule(document)
            if not rule:
                continue
            if not _rule_applies_to_language(rule, language):
                continue
            finding = _finding_for_rule(
                rule=rule,
                file_path=file_path,
                lines=lines,
                full_text=added_text,
                diff_text=diff_text,
                changed_files=changed_files,
                project_context=project_context,
            )
            if not finding:
                continue
            signature = (
                finding["rule_family"],
                finding["file_path"],
                int(finding["line_number"]),
            )
            if signature in seen:
                continue
            seen.add(signature)
            findings.append(finding)

    logger.info("RAG risk review produced %d finding(s).", len(findings))
    return findings
