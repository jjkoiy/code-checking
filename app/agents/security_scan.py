"""Security Scan Agent — pattern-based security vulnerability detection."""

from __future__ import annotations

import re
import logging

from app.agents.diff_utils import detect_language, is_code_file, review_text_by_file
from app.agents.evidence_extractor import extract_evidence, line_span_for_match

logger = logging.getLogger(__name__)

_CHECKS: list[dict] = [
    {
        "id": "SEC001",
        "title": "Potential SQL injection via f-string",
        "severity": "critical",
        "pattern": re.compile(
            r"(?:f\"[^\"]*?\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b"
            r"|f'[^']*?\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b)",
            re.IGNORECASE,
        ),
        "description": "SQL query built with f-string interpolation allows SQL injection attacks.",
        "attack_scenario": "An attacker could inject malicious SQL via user-controlled input interpolated into the query string.",
        "suggestion": "Use parameterized queries: SQLAlchemy text() with bindparams, psycopg2 %s placeholders, or an ORM.",
    },
    {
        "id": "SEC001b",
        "title": "Variable named query/sql assigned to f-string",
        "severity": "high",
        "pattern": re.compile(
            r"(?:query|sql|cursor)\s*=\s*f[\"'][^\"']*\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b",
            re.IGNORECASE,
        ),
        "description": "A variable named query/sql/cursor assigned to an f-string suggests dynamic SQL construction.",
        "attack_scenario": "Dynamic SQL without proper parameterization is vulnerable to SQL injection.",
        "suggestion": "Use parameterized queries or an ORM. If dynamic table/column names are needed, validate against an allowlist.",
    },
    {
        "id": "SEC002",
        "title": "Hardcoded secret or credential",
        "severity": "critical",
        "pattern": re.compile(
            r"(?i)(?:password|secret|api_key|apikey|token|access_key|private_key|auth_token)\s*[:=]\s*[\"'][^\"']{4,}[\"']"
        ),
        "description": "A secret or credential appears to be hardcoded in source code.",
        "attack_scenario": "Secrets committed to version control are exposed to anyone with repository access and persist in git history.",
        "suggestion": "Use environment variables (os.getenv) or a secrets manager (AWS Secrets Manager, HashiCorp Vault).",
    },
    {
        "id": "SEC003",
        "title": "Potential command injection",
        "severity": "critical",
        "pattern": re.compile(
            r"(?:\bos\.system\s*\(|\bsubprocess\.(?:call|run|Popen)\s*\([^)]*\bshell\s*=\s*True\b|\bshell\s*=\s*True\b)",
            re.MULTILINE | re.DOTALL,
        ),
        "description": "Shell command execution with user-controlled input may allow command injection.",
        "attack_scenario": "An attacker could inject shell metacharacters (;, |, &&, $()) to execute arbitrary commands.",
        "suggestion": "Avoid shell=True. Use subprocess.run() with a list of arguments instead of a string. Sanitize all user inputs passed to shell commands.",
    },
    {
        "id": "SEC004",
        "title": "Use of dangerous eval/exec",
        "severity": "critical",
        "pattern": re.compile(r"\b(?:eval|exec|compile)\s*\(", re.MULTILINE),
        "description": "eval() and exec() execute arbitrary code and are extremely dangerous with user input.",
        "attack_scenario": "An attacker could execute arbitrary Python code on the server via user-controlled input to eval().",
        "suggestion": "Remove eval/exec entirely. If dynamic dispatch is needed, use a lookup table or importlib.",
    },
    {
        "id": "SEC005",
        "title": "Insecure deserialization",
        "severity": "high",
        "pattern": re.compile(r"\b(?:pickle\.(?:loads?|dump)|yaml\.load\b|marshal\.loads?)\s*\(", re.MULTILINE),
        "description": "Deserializing untrusted data with pickle, yaml.load, or marshal can lead to arbitrary code execution.",
        "attack_scenario": "An attacker could craft a malicious pickle payload that executes code when deserialized.",
        "suggestion": "Use yaml.safe_load() instead of yaml.load(), and never deserialize pickle/marshal data from untrusted sources.",
    },
    {
        "id": "SEC006",
        "title": "Weak hash algorithm",
        "severity": "medium",
        "pattern": re.compile(r"\b(?:md5|sha1)\s*\(", re.IGNORECASE),
        "description": "MD5 and SHA1 are cryptographically broken and should not be used for security purposes.",
        "attack_scenario": "Collision attacks against MD5/SHA1 can allow an attacker to forge signatures or bypass integrity checks.",
        "suggestion": "Use hashlib.sha256() or stronger. For passwords, use bcrypt, scrypt, or argon2 via a dedicated library.",
    },
    {
        "id": "SEC007",
        "title": "HTTP instead of HTTPS",
        "severity": "medium",
        "pattern": re.compile(r'["\']http://[^"\']*["\']', re.MULTILINE),
        "description": "Hardcoded HTTP URLs may leak sensitive data in transit.",
        "attack_scenario": "Data sent over HTTP can be intercepted via man-in-the-middle attacks.",
        "suggestion": "Use HTTPS URLs. If HTTP must be used for local development, gate it behind an environment check.",
    },
    {
        "id": "SEC008",
        "title": "Debug mode enabled",
        "severity": "low",
        "pattern": re.compile(r"(?i)\bdebug\s*=\s*True\b", re.MULTILINE),
        "description": "Debug mode enabled in production can leak stack traces and sensitive configuration details.",
        "attack_scenario": "Error pages with debug info expose file paths, code snippets, and environment details.",
        "suggestion": "Set debug=False and control it via an environment variable (e.g., APP_ENV).",
    },
]


def _find_diff_lines(diff_text: str) -> set[int]:
    changed: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_text, re.MULTILINE):
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) else 1
        for ln in range(start, start + count):
            changed.add(ln)
    return changed


def _is_low_risk_http_literal(evidence: str) -> bool:
    lowered = evidence.lower()
    return any(host in lowered for host in ("http://localhost", "http://127.0.0.1", "http://0.0.0.0"))


def _looks_like_placeholder_secret(evidence: str) -> bool:
    lowered = evidence.lower()
    placeholders = (
        "example",
        "changeme",
        "change-me",
        "dummy",
        "fake",
        "placeholder",
        "test-token",
        "test_secret",
        "your-token",
        "your_token",
    )
    return any(token in lowered for token in placeholders)


def _finding_confidence(check_id: str, evidence: str) -> float:
    if check_id == "SEC002" and _looks_like_placeholder_secret(evidence):
        return 0.45
    if check_id == "SEC007" and _is_low_risk_http_literal(evidence):
        return 0.45
    if check_id in {"SEC001", "SEC003", "SEC004"}:
        return 0.86
    return 0.80


def scan(diff_text: str, changed_files: list[dict]) -> list[dict]:
    """Scan diff text for security vulnerabilities. Returns list of Finding dicts."""
    findings: list[dict] = []
    review_text = review_text_by_file(diff_text, changed_files)
    if not review_text:
        return findings
    languages_by_file = {
        f.get("file_path"): f.get("language")
        for f in changed_files
        if f.get("file_path")
    }

    for check in _CHECKS:
        for file_path, (added_text, line_numbers) in review_text.items():
            language = languages_by_file.get(file_path) or detect_language(file_path)
            if not is_code_file(file_path, language):
                continue
            for m in check["pattern"].finditer(added_text):
                line_start, line_end = line_span_for_match(line_numbers, added_text, m.start(), m.end())
                evidence = extract_evidence(diff_text, changed_files, file_path, line_start, line_end)
                confidence = _finding_confidence(check["id"], evidence)
                if confidence < 0.5:
                    continue

                findings.append({
                    "agent_name": "security_agent",
                    "severity": check["severity"],
                    "category": "security",
                    "file_path": file_path,
                    "line_number": line_start,
                    "line_start": line_start,
                    "line_end": line_end,
                    "title": check["title"],
                    "description": check["description"],
                    "evidence": evidence,
                    "attack_scenario": check.get("attack_scenario", ""),
                    "suggestion": check["suggestion"],
                    "confidence": confidence,
                })

    logger.info("Security scan produced %d finding(s).", len(findings))
    return findings
