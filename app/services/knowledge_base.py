from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.vector_store import vector_upsert

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


def _document_id(repo_name: str, file_path: str, chunk_index: int, content: str) -> str:
    raw = f"{repo_name}:{file_path}:{chunk_index}:{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def index_repository(repo_name: str | None, repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("repo_path must point to an existing directory")

    resolved_repo_name = repo_name or root.name
    max_files = max(1, settings.knowledge_max_files)
    max_file_chars = max(1, settings.knowledge_max_file_chars)
    chunk_chars = max(200, settings.knowledge_chunk_chars)
    documents: list[dict[str, Any]] = []
    indexed_files = 0
    skipped_files = 0

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
        file_chunks = _chunks(text, chunk_chars)
        if not file_chunks:
            skipped_files += 1
            continue
        indexed_files += 1
        for chunk_index, chunk in enumerate(file_chunks):
            documents.append({
                "id": _document_id(resolved_repo_name, relative_path, chunk_index, chunk),
                "content": chunk,
                "metadata": {
                    "repo_name": resolved_repo_name,
                    "file_path": relative_path,
                    "chunk_index": chunk_index,
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
        "embedding_skipped": bool(upsert_result.get("skipped")),
        "skip_reason": upsert_result.get("skip_reason"),
    }
