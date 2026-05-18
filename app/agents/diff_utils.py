from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path


_CODE_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "go",
    "rust",
    "java",
    "kotlin",
    "swift",
    "ruby",
    "php",
    "csharp",
    "sql",
    "shell",
    "yaml",
    "json",
    "hcl",
    "dockerfile",
}

_CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".rb",
    ".php",
    ".cs",
    ".sql",
    ".sh",
    ".bash",
    ".yaml",
    ".yml",
    ".json",
    ".tf",
    ".dockerfile",
}


def detect_language(file_path: str | None) -> str | None:
    if not file_path:
        return None

    path = Path(file_path)
    if path.name.lower() == "dockerfile":
        return "dockerfile"

    suffix = path.suffix.lower()
    extension_to_language = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
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
    return extension_to_language.get(suffix)


def is_code_file(file_path: str | None, language: str | None = None) -> bool:
    """Return whether a changed path should be treated as source/config code."""
    normalized_language = (language or "").lower()
    if normalized_language in _CODE_LANGUAGES:
        return True
    if not file_path:
        return False

    path = Path(file_path)
    if path.name.lower() == "dockerfile":
        return True
    return path.suffix.lower() in _CODE_EXTENSIONS


def _infer_raw_code_path(diff_text: str, fallback_file_path: str | None) -> tuple[str | None, int]:
    if fallback_file_path and is_code_file(fallback_file_path):
        return fallback_file_path, 0

    lines = diff_text.splitlines()
    for index, raw_line in enumerate(lines[:8]):
        line = raw_line.strip()
        heading_match = re.match(r"^#{1,6}\s+`?([^`\s]+)`?\s*$", line)
        if not heading_match:
            continue
        candidate = heading_match.group(1)
        if is_code_file(candidate):
            return candidate, index + 1
    return None, 0


def iter_added_lines(diff_text: str) -> Iterator[tuple[str, int, str]]:
    """Yield (file_path, new_line_number, line_text) for added lines in a unified diff."""
    current_file: str | None = None
    new_line: int | None = None

    for raw_line in diff_text.splitlines():
        file_match = re.match(r"^diff --git a/(.+?) b/(.+?)$", raw_line)
        if file_match:
            current_file = file_match.group(2)
            new_line = None
            continue

        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw_line)
        if hunk_match:
            new_line = int(hunk_match.group(1))
            continue

        if current_file is None or new_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            yield current_file, new_line, raw_line[1:]
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            new_line += 1


def added_text_by_file(
    diff_text: str,
    fallback_file_path: str | None = None,
    allow_raw: bool = False,
) -> dict[str, tuple[str, list[int]]]:
    """Return added text grouped by file plus a line-number map for match offsets."""
    grouped: dict[str, list[tuple[int, str]]] = {}
    for file_path, line_number, line_text in iter_added_lines(diff_text):
        grouped.setdefault(file_path, []).append((line_number, line_text))

    result: dict[str, tuple[str, list[int]]] = {}
    for file_path, lines in grouped.items():
        result[file_path] = (
            "\n".join(line_text for _, line_text in lines),
            [line_number for line_number, _ in lines],
        )
    if result or not allow_raw or not diff_text.strip():
        return result

    file_path, start_index = _infer_raw_code_path(diff_text, fallback_file_path)
    if not file_path:
        return result

    raw_lines = diff_text.splitlines()[start_index:]
    result[file_path] = (
        "\n".join(raw_lines),
        list(range(start_index + 1, start_index + len(raw_lines) + 1)),
    )
    return result
