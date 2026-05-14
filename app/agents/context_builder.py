"""Context Builder Agent — parses diff, detects languages, builds project context."""

from __future__ import annotations

import re
import logging
from pathlib import Path

from app.services.vector_store import vector_search

logger = logging.getLogger(__name__)

_LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".tf": "hcl",
    ".dockerfile": "dockerfile",
}

_RISK_KEYWORDS = [
    "auth", "token", "password", "secret", "key", "credential",
    "sql", "query", "execute", "subprocess", "eval", "exec",
    "upload", "download", "serialize", "deserialize", "crypto",
    "permission", "role", "admin", "webhook", "callback",
]


def _detect_language(file_path: str) -> str:
    p = Path(file_path)
    if p.name.lower() == "dockerfile":
        return "dockerfile"
    suffix = p.suffix.lower()
    return _LANG_MAP.get(suffix, "unknown")


def parse_diff(diff_text: str) -> list[dict]:
    """Parse unified diff text into structured changed-file entries."""
    if not diff_text:
        return []

    files: list[dict] = []
    file_re = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
    change_re = re.compile(r"^(new file mode|deleted file mode|rename from|rename to)", re.MULTILINE)
    chunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    parts = re.split(r"^(?=diff --git )", diff_text, flags=re.MULTILINE)
    for part in parts:
        if not part.startswith("diff --git "):
            continue
        lines = part.split("\n")
        header = lines[0]
        m = file_re.match(header)
        if not m:
            continue
        file_path = m.group(2) if m.group(2) != "/dev/null" else m.group(1)

        added = 0
        deleted = 0
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                deleted += 1

        change_type = "modified"
        joined = "\n".join(lines[1:])
        if re.search(r"^new file mode", joined, re.MULTILINE):
            change_type = "added"
        elif re.search(r"^deleted file mode", joined, re.MULTILINE):
            change_type = "deleted"

        files.append({
            "file_path": file_path,
            "change_type": change_type,
            "language": _detect_language(file_path),
            "added_lines": added,
            "deleted_lines": deleted,
        })

    return files


def build_context(diff_text: str, changed_files: list[dict] | None = None) -> dict:
    """Build project_context from diff and changed files."""
    if changed_files is None:
        changed_files = parse_diff(diff_text)

    languages = list({f.get("language", "unknown") for f in changed_files})
    changed_modules = [f["file_path"] for f in changed_files]

    diff_lower = diff_text.lower()
    risk_hints = [kw for kw in _RISK_KEYWORDS if kw in diff_lower]
    search_query = " ".join(changed_modules + risk_hints + languages) or diff_text[:500]
    relevant_rules: list[dict] = []
    relevant_test_examples: list[dict] = []
    try:
        relevant_rules.extend(vector_search("review_rules", search_query, top_k=3)["documents"])
        relevant_rules.extend(vector_search("security_rules", search_query, top_k=3)["documents"])
        relevant_test_examples.extend(vector_search("test_examples", search_query, top_k=3)["documents"])
    except Exception as e:
        logger.warning("Vector context lookup skipped: %s", e)

    return {
        "languages": languages,
        "changed_modules": changed_modules,
        "risk_hints": risk_hints,
        "relevant_rules": relevant_rules,
        "relevant_test_examples": relevant_test_examples,
        "context_summary": (
            f"{len(changed_files)} file(s) changed in {len(languages)} language(s). "
            f"Risk keywords found: {', '.join(risk_hints) if risk_hints else 'none'}."
        ),
    }
