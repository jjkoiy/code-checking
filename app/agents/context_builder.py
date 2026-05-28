"""Context Builder Agent — parses diff, detects languages, builds project context."""

from __future__ import annotations

import re
import logging
from pathlib import Path

from app.config import settings
from app.agents.diff_utils import review_text_by_file
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


def _resolved_repo_name(repo_name: str | None, repo_path: str | None) -> str | None:
    if repo_name:
        return repo_name
    if repo_path:
        return Path(repo_path).expanduser().resolve().name
    return None


def _extend_unique(target: list[dict], incoming: list[dict]) -> None:
    seen = {
        str(item.get("id") or item.get("content") or index)
        for index, item in enumerate(target)
    }
    for item in incoming:
        doc_id = str(item.get("id") or item.get("content") or len(seen))
        if doc_id in seen:
            continue
        seen.add(doc_id)
        target.append(item)


def _record_retrieval(
    retrievals: list[dict],
    result: dict,
    collection: str,
) -> None:
    retrieval = result.get("retrieval")
    if isinstance(retrieval, dict):
        retrievals.append(retrieval)
    else:
        retrievals.append({
            "collection": collection,
            "document_count": len(result.get("documents", [])),
            "vector_skipped": bool(result.get("skipped")),
            "skip_reason": result.get("skip_reason"),
        })


def _rag_summary(retrievals: list[dict], skip_reasons: list[str]) -> dict:
    by_collection: dict[str, int] = {}
    vector_skip_reasons: list[str] = []
    for retrieval in retrievals:
        collection = str(retrieval.get("collection", "unknown"))
        by_collection[collection] = by_collection.get(collection, 0) + int(
            retrieval.get("document_count", 0) or 0
        )
        if retrieval.get("vector_skipped") and retrieval.get("skip_reason"):
            vector_skip_reasons.append(str(retrieval["skip_reason"]))
    first = retrievals[0] if retrievals else {}
    all_skip_reasons = list(dict.fromkeys(skip_reasons + vector_skip_reasons))
    return {
        "retrieval_mode": first.get("retrieval_mode", settings.rag_retrieval_mode),
        "embedding_provider": first.get("embedding_provider", settings.embedding_provider),
        "embedding_model": first.get("embedding_model", settings.embedding_model),
        "document_count": sum(by_collection.values()),
        "collections": by_collection,
        "skipped": bool(all_skip_reasons),
        "vector_skipped": bool(vector_skip_reasons),
        "degraded": bool(vector_skip_reasons),
        "skip_reasons": all_skip_reasons,
    }


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


def build_context(
    diff_text: str,
    changed_files: list[dict] | None = None,
    repo_name: str | None = None,
    repo_path: str | None = None,
) -> dict:
    """Build project_context from diff and changed files."""
    if changed_files is None:
        changed_files = parse_diff(diff_text)

    languages = list({f.get("language", "unknown") for f in changed_files})
    changed_modules = [f["file_path"] for f in changed_files]

    diff_lower = diff_text.lower()
    risk_hints = [kw for kw in _RISK_KEYWORDS if kw in diff_lower]
    review_text = review_text_by_file(diff_text, changed_files)
    file_queries: list[tuple[str, str]] = []
    for changed in changed_files:
        file_path = changed.get("file_path", "")
        language = changed.get("language") or _detect_language(file_path)
        snippet = review_text.get(file_path, ("", []))[0][:2000]
        query = "\n".join([
            f"file:{file_path}",
            f"language:{language}",
            "risk:" + " ".join(risk_hints),
            snippet,
        ]).strip()
        if query:
            file_queries.append((file_path, query))
    if not file_queries:
        search_query = " ".join(changed_modules + risk_hints + languages) or diff_text[:500]
        file_queries.append(("", search_query))
    resolved_repo_name = _resolved_repo_name(repo_name, repo_path)
    relevant_rules: list[dict] = []
    relevant_test_examples: list[dict] = []
    relevant_project_context: list[dict] = []
    retrievals: list[dict] = []
    knowledge_skipped = False
    knowledge_skip_reasons: list[str] = []
    try:
        for _file_path, search_query in file_queries:
            for collection in ("review_rules", "security_rules"):
                result = vector_search(collection, search_query, top_k=3)
                _extend_unique(relevant_rules, result["documents"])
                _record_retrieval(retrievals, result, collection)
                if result.get("skipped"):
                    knowledge_skipped = True
                    knowledge_skip_reasons.append(str(result.get("skip_reason", collection)))
            result = vector_search("test_examples", search_query, top_k=3)
            _extend_unique(relevant_test_examples, result["documents"])
            _record_retrieval(retrievals, result, "test_examples")
            if result.get("skipped"):
                knowledge_skipped = True
                knowledge_skip_reasons.append(str(result.get("skip_reason", "test_examples")))
            if resolved_repo_name:
                result = vector_search(
                    "repository_context",
                    search_query,
                    top_k=max(1, settings.rag_vector_top_k),
                    where={"repo_name": resolved_repo_name},
                )
                _extend_unique(relevant_project_context, result["documents"])
                _record_retrieval(retrievals, result, "repository_context")
                if result.get("skipped"):
                    knowledge_skipped = True
                    knowledge_skip_reasons.append(str(result.get("skip_reason", "repository_context")))
    except Exception as e:
        knowledge_skipped = True
        knowledge_skip_reasons.append(str(e))
        logger.warning("Vector context lookup skipped: %s", e)

    return {
        "languages": languages,
        "changed_modules": changed_modules,
        "risk_hints": risk_hints,
        "relevant_rules": relevant_rules,
        "relevant_test_examples": relevant_test_examples,
        "relevant_project_context": relevant_project_context,
        "knowledge_skipped": knowledge_skipped,
        "knowledge_skip_reasons": knowledge_skip_reasons,
        "rag": _rag_summary(retrievals, knowledge_skip_reasons),
        "retrieval_trace": retrievals,
        "context_summary": (
            f"{len(changed_files)} file(s) changed in {len(languages)} language(s). "
            f"Risk keywords found: {', '.join(risk_hints) if risk_hints else 'none'}."
        ),
    }
