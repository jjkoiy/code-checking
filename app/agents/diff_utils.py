from __future__ import annotations

import re
from collections.abc import Iterator


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


def added_text_by_file(diff_text: str) -> dict[str, tuple[str, list[int]]]:
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
    return result
