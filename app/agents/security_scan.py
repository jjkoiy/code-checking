"""Security Scan Agent — pattern-based security vulnerability detection."""

from __future__ import annotations

import re
import logging

from app.agents.diff_utils import added_text_by_file

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
            r"(?:query|sql|cursor)\s*=\s*f[\"']",
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
            r"(?:os\.system|subprocess\.(?:call|run|Popen)|shell\s*=\s*True)",
            re.MULTILINE,
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


def _line_number(text: str, match_start: int) -> int:
    return text[:match_start].count("\n") + 1


def _find_diff_lines(diff_text: str) -> set[int]:
    changed: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_text, re.MULTILINE):
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) else 1
        for ln in range(start, start + count):
            changed.add(ln)
    return changed


def scan(diff_text: str, changed_files: list[dict]) -> list[dict]:
    """Scan diff text for security vulnerabilities. Returns list of Finding dicts."""
    if not diff_text:
        return []

    findings: list[dict] = []
    added_by_file = added_text_by_file(diff_text)
    if not added_by_file:
        return findings

    for check in _CHECKS:
        for file_path, (added_text, line_numbers) in added_by_file.items():
            for m in check["pattern"].finditer(added_text):
                added_index = _line_number(added_text, m.start()) - 1
                linenum = line_numbers[added_index] if added_index < len(line_numbers) else None
                evidence = added_text[max(0, m.start() - 20):m.end() + 40].strip().replace("\n", " ")[:200]

                findings.append({
                    "agent_name": "security_agent",
                    "severity": check["severity"],
                    "category": "security",
                    "file_path": file_path,
                    "line_number": linenum,
                    "title": check["title"],
                    "description": check["description"],
                    "evidence": evidence,
                    "attack_scenario": check.get("attack_scenario", ""),
                    "suggestion": check["suggestion"],
                    "confidence": 0.80,
                })

    logger.info("Security scan produced %d finding(s).", len(findings))
    return findings
