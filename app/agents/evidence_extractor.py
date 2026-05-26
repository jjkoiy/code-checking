"""Evidence extraction helpers for report-quality-safe findings."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceLine:
    file_path: str
    line_number: int
    text: str
    is_added: bool = True


def _parse_diff_lines(diff_text: str) -> dict[str, list[EvidenceLine]]:
    by_file: dict[str, list[EvidenceLine]] = {}
    current_file: str | None = None
    new_line: int | None = None

    for raw_line in diff_text.splitlines():
        file_match = re.match(r"^diff --git a/(.+?) b/(.+?)$", raw_line)
        if file_match:
            current_file = file_match.group(2)
            new_line = None
            by_file.setdefault(current_file, [])
            continue

        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw_line)
        if hunk_match:
            new_line = int(hunk_match.group(1))
            continue

        if current_file is None or new_line is None:
            continue
        if raw_line.startswith("+++") or raw_line.startswith("---"):
            continue

        if raw_line.startswith("+"):
            by_file.setdefault(current_file, []).append(
                EvidenceLine(current_file, new_line, raw_line[1:], True)
            )
            new_line += 1
        elif raw_line.startswith("-"):
            continue
        else:
            text = raw_line[1:] if raw_line.startswith(" ") else raw_line
            by_file.setdefault(current_file, []).append(
                EvidenceLine(current_file, new_line, text, False)
            )
            new_line += 1

    return by_file


def _raw_content_lines(changed_files: list[dict]) -> dict[str, list[EvidenceLine]]:
    by_file: dict[str, list[EvidenceLine]] = {}
    for changed in changed_files:
        file_path = changed.get("file_path")
        content = changed.get("content")
        if not file_path or not isinstance(content, str):
            continue
        by_file[file_path] = [
            EvidenceLine(file_path, line_number, text, True)
            for line_number, text in enumerate(content.splitlines(), start=1)
        ]
    return by_file


def evidence_sources(diff_text: str, changed_files: list[dict]) -> dict[str, list[EvidenceLine]]:
    """Return source lines keyed by file, preferring unified diff hunks over raw content."""
    diff_sources = _parse_diff_lines(diff_text)
    raw_sources = _raw_content_lines(changed_files)
    merged = dict(raw_sources)
    merged.update({path: lines for path, lines in diff_sources.items() if lines})
    if not merged and diff_text.strip():
        fallback_file_path = next(
            (item.get("file_path") for item in changed_files if item.get("file_path")),
            None,
        )
        start_index = 0
        if not fallback_file_path:
            lines = diff_text.splitlines()
            for index, raw_line in enumerate(lines[:8]):
                heading_match = re.match(r"^#{1,6}\s+`?([^`\s]+)`?\s*$", raw_line.strip())
                if heading_match:
                    fallback_file_path = heading_match.group(1)
                    start_index = index + 1
                    break
        if fallback_file_path:
            raw_lines = diff_text.splitlines()[start_index:]
            merged[fallback_file_path] = [
                EvidenceLine(fallback_file_path, line_number, text, True)
                for line_number, text in enumerate(raw_lines, start=start_index + 1)
            ]
    return merged


def extract_evidence(
    diff_text: str,
    changed_files: list[dict],
    file_path: str | None,
    line_start: int | None,
    line_end: int | None = None,
    context_lines: int = 0,
) -> str:
    """Extract evidence from original diff/source without character-window slicing."""
    if not file_path or line_start is None:
        return ""

    sources = evidence_sources(diff_text, changed_files).get(file_path, [])
    if not sources:
        return ""

    end = line_end if line_end is not None else line_start
    if end < line_start:
        end = line_start
    start_with_context = max(1, line_start - max(context_lines, 0))
    end_with_context = end + max(context_lines, 0)
    selected = [
        item.text
        for item in sources
        if start_with_context <= item.line_number <= end_with_context
    ]
    return "\n".join(selected)


def line_span_for_match(line_numbers: list[int], text: str, match_start: int, match_end: int) -> tuple[int | None, int | None]:
    """Map a regex match character span in review text to original line numbers."""
    if not line_numbers:
        return None, None
    start_index = text[:match_start].count("\n")
    end_index = text[: max(match_start, match_end - 1)].count("\n")
    line_start = line_numbers[start_index] if start_index < len(line_numbers) else None
    line_end = line_numbers[end_index] if end_index < len(line_numbers) else line_start
    return line_start, line_end
