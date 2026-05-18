"""Test Impact Agent for P2."""

from __future__ import annotations

import logging
from pathlib import Path

from app.agents.diff_utils import is_code_file
from app.services.vector_store import vector_search

logger = logging.getLogger(__name__)

_TEST_PATH_MARKERS = ("test", "tests", "spec", "__tests__")


def _module_name(file_path: str) -> str:
    path = Path(file_path)
    return path.stem or file_path


def _guess_existing_tests(file_path: str, language: str | None) -> list[str]:
    path = Path(file_path)
    stem = path.stem
    if any(marker in path.parts for marker in _TEST_PATH_MARKERS):
        return [file_path]
    if language == "python":
        return [f"tests/test_{stem}.py"]
    if language in {"javascript", "typescript"}:
        suffix = path.suffix.lstrip(".") or "js"
        return [f"{path.parent}/{stem}.test.{suffix}".replace("\\", "/")]
    return []


def analyze(changed_files: list[dict], diff_text: str) -> dict:
    """Return a heuristic test impact assessment for changed files."""
    affected_modules: list[str] = []
    recommended_test_types: set[str] = set()
    existing_tests_to_run: list[str] = []
    new_tests_needed: list[dict] = []
    coverage_gaps: list[str] = []

    diff_lower = diff_text.lower()
    high_risk_keywords = {
        "auth": "integration",
        "permission": "integration",
        "role": "integration",
        "sql": "security",
        "query": "security",
        "payment": "integration",
        "api": "integration",
        "router": "integration",
        "exception": "unit",
        "error": "unit",
    }

    for changed in changed_files:
        file_path = changed.get("file_path", "")
        language = changed.get("language")
        if not file_path:
            continue
        if not is_code_file(file_path, language):
            continue

        file_test_types: set[str] = set()
        module = _module_name(file_path)
        affected_modules.append(module)
        guessed_tests = _guess_existing_tests(file_path, language)
        existing_tests_to_run.extend(guessed_tests)
        if not guessed_tests:
            coverage_gaps.append(f"No obvious test file mapped for {file_path}")

        if language == "python":
            file_test_types.add("unit")
        if "api" in file_path.lower() or "router" in file_path.lower():
            file_test_types.add("integration")

        for keyword, test_type in high_risk_keywords.items():
            if keyword in diff_lower or keyword in file_path.lower():
                file_test_types.add(test_type)

        recommended_test_types.update(file_test_types)

        new_tests_needed.append({
            "module": module,
            "file_path": file_path,
            "reason": "Changed file should have regression coverage for touched behavior.",
            "suggested_test_types": sorted(file_test_types),
        })

    relevant_examples: list[dict] = []
    try:
        query = " ".join(affected_modules) + " " + " ".join(sorted(recommended_test_types))
        relevant_examples = vector_search("test_examples", query, top_k=3)["documents"] if query.strip() else []
    except Exception as e:
        logger.warning("Test impact vector lookup skipped: %s", e)

    logger.info("Test impact produced %d affected module(s).", len(affected_modules))
    return {
        "affected_modules": sorted(set(affected_modules)),
        "recommended_test_types": sorted(recommended_test_types),
        "existing_tests_to_run": sorted(set(existing_tests_to_run)),
        "new_tests_needed": new_tests_needed,
        "coverage_gaps": coverage_gaps,
        "relevant_test_examples": relevant_examples,
    }
