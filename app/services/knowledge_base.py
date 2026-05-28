from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.llm_safety import redact_text
from app.services.vector_store import vector_delete_where, vector_upsert

_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "data",
    "myenv",
    "node_modules",
}

_INDEXABLE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".sql",
    ".sh",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".md",
    ".txt",
    ".dockerfile",
}


def _is_indexable(path: Path) -> bool:
    if any(part in _EXCLUDED_DIRS for part in path.parts):
        return False
    if path.name.lower() == "dockerfile":
        return True
    return path.suffix.lower() in _INDEXABLE_SUFFIXES


def _chunks(text: str, chunk_chars: int) -> list[str]:
    size = max(200, chunk_chars)
    return [text[index:index + size] for index in range(0, len(text), size) if text[index:index + size].strip()]


def _detect_language(path: Path) -> str:
    if path.name.lower() == "dockerfile":
        return "dockerfile"
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".sql": "sql",
        ".sh": "shell",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".toml": "toml",
        ".md": "markdown",
        ".txt": "text",
    }.get(path.suffix.lower(), "unknown")


def _lines_between(lines: list[str], start_line: int, end_line: int) -> str:
    return "\n".join(lines[start_line - 1:end_line]).strip("\n")


def _window_chunks(
    text: str,
    chunk_chars: int,
    language: str,
    overlap_lines: int = 2,
) -> list[dict[str, Any]]:
    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    start_index = 0
    while start_index < len(lines):
        current: list[str] = []
        end_index = start_index
        while end_index < len(lines):
            candidate = current + [lines[end_index]]
            if current and len("\n".join(candidate)) > chunk_chars:
                break
            current = candidate
            end_index += 1
        content = "\n".join(current).strip()
        if content:
            chunks.append({
                "content": content,
                "start_line": start_index + 1,
                "end_line": end_index,
                "symbol_name": "",
                "chunk_type": "window" if language not in {"markdown", "text"} else "section",
                "language": language,
            })
        if end_index >= len(lines):
            break
        start_index = max(end_index - overlap_lines, start_index + 1)
    return chunks


def _python_symbol_chunks(text: str, chunk_chars: int) -> list[dict[str, Any]]:
    redacted_text = redact_text(text)
    redacted_lines = redacted_text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _window_chunks(redacted_text, chunk_chars, "python")

    chunks: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start_line = int(getattr(node, "lineno", 1))
        end_line = int(getattr(node, "end_lineno", start_line))
        content = _lines_between(redacted_lines, start_line, end_line)
        if not content.strip():
            continue
        chunk_type = "class" if isinstance(node, ast.ClassDef) else "function"
        if len(content) <= chunk_chars:
            chunks.append({
                "content": content,
                "start_line": start_line,
                "end_line": end_line,
                "symbol_name": node.name,
                "chunk_type": chunk_type,
                "language": "python",
            })
        else:
            for part in _window_chunks(content, chunk_chars, "python"):
                offset_start = start_line + int(part["start_line"]) - 1
                offset_end = start_line + int(part["end_line"]) - 1
                chunks.append({
                    **part,
                    "start_line": offset_start,
                    "end_line": offset_end,
                    "symbol_name": node.name,
                    "chunk_type": chunk_type,
                })

    if chunks:
        return chunks
    return _window_chunks(redacted_text, chunk_chars, "python")


def _structured_chunks(text: str, file_path: str, chunk_chars: int) -> list[dict[str, Any]]:
    language = _detect_language(Path(file_path))
    if language == "python":
        return _python_symbol_chunks(text, chunk_chars)
    return _window_chunks(redact_text(text), chunk_chars, language)


def _document_id(repo_name: str, file_path: str, chunk_index: int, content: str) -> str:
    raw = f"{repo_name}:{file_path}:{chunk_index}:{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _hash_text(value: str, length: int = 32) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def index_repository(repo_name: str | None, repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("repo_path must point to an existing directory")

    resolved_repo_name = repo_name or root.name
    repo_path_hash = _hash_text(str(root), length=16)
    max_files = max(1, settings.knowledge_max_files)
    max_file_chars = max(1, settings.knowledge_max_file_chars)
    chunk_chars = max(200, settings.knowledge_chunk_chars)
    documents: list[dict[str, Any]] = []
    indexed_files = 0
    skipped_files = 0
    delete_result = vector_delete_where(
        "repository_context",
        {"repo_name": resolved_repo_name},
    )

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if not _is_indexable(relative):
            skipped_files += 1
            continue
        if indexed_files >= max_files:
            skipped_files += 1
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped_files += 1
            continue
        if len(text) > max_file_chars:
            skipped_files += 1
            continue

        relative_path = relative.as_posix()
        file_chunks = _structured_chunks(text, relative_path, chunk_chars)
        if not file_chunks:
            skipped_files += 1
            continue
        indexed_files += 1
        for chunk_index, chunk in enumerate(file_chunks):
            content = str(chunk["content"])
            content_hash = _hash_text(content)
            documents.append({
                "id": _document_id(resolved_repo_name, relative_path, chunk_index, content),
                "content": content,
                "metadata": {
                    "repo_name": resolved_repo_name,
                    "repo_path_hash": repo_path_hash,
                    "file_path": relative_path,
                    "chunk_index": chunk_index,
                    "content_hash": content_hash,
                    "start_line": int(chunk.get("start_line", 1)),
                    "end_line": int(chunk.get("end_line", 1)),
                    "symbol_name": str(chunk.get("symbol_name", "")),
                    "chunk_type": str(chunk.get("chunk_type", "window")),
                    "language": str(chunk.get("language", _detect_language(relative))),
                },
            })

    upsert_result = vector_upsert("repository_context", documents)
    return {
        "status": "skipped" if upsert_result.get("skipped") else "indexed",
        "repo_name": resolved_repo_name,
        "repo_path": str(root),
        "indexed_files": indexed_files if not upsert_result.get("skipped") else 0,
        "indexed_chunks": int(upsert_result.get("indexed_count", 0)),
        "skipped_files": skipped_files,
        "deleted_chunks": int(delete_result.get("deleted_count", 0)),
        "embedding_skipped": bool(upsert_result.get("skipped")),
        "skip_reason": upsert_result.get("skip_reason"),
    }


def _risk_rule_document_id(risk_id: str, content: str) -> str:
    raw = f"risk_rules:{risk_id}:{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def import_risk_rules(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Index structured risk cards used by the RAG risk review agent."""
    documents: list[dict[str, Any]] = []
    for rule in rules:
        risk_id = str(rule.get("risk_id", "")).strip()
        content = json.dumps(rule, ensure_ascii=False, sort_keys=True)
        documents.append({
            "id": _risk_rule_document_id(risk_id, content),
            "content": content,
            "metadata": {
                "risk_id": risk_id,
                "title": str(rule.get("title", "")),
                "category": str(rule.get("category", "security")),
                "severity": str(rule.get("severity", "medium")),
                "rule_family": risk_id,
                "cwe": str(rule.get("cwe", "")),
                "languages": ",".join(str(item) for item in rule.get("languages", []) or []),
                "frameworks": ",".join(str(item) for item in rule.get("frameworks", []) or []),
                "sanitizer_patterns": ",".join(str(item) for item in rule.get("sanitizer_patterns", []) or []),
            },
        })

    upsert_result = vector_upsert("risk_rules", documents)
    return {
        "status": "skipped" if upsert_result.get("skipped") else "indexed",
        "indexed_rules": int(upsert_result.get("indexed_count", 0)),
        "embedding_skipped": bool(upsert_result.get("skipped")),
        "skip_reason": upsert_result.get("skip_reason"),
    }
