"""Test Generation Agent for P2."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings
from app.services.llm_client import call_llm
from app.services.llm_safety import external_llm_enabled, llm_mode, redact_text

logger = logging.getLogger(__name__)

TEST_GENERATION_SYSTEM_PROMPT = """You are the Test Generation Agent.
Return only JSON with keys test_plan, generated_tests, notes.
Generated tests may be draft code, but must be marked as not executed."""


def _default_test_name(file_path: str, test_type: str) -> str:
    stem = Path(file_path).stem or "change"
    safe_type = test_type.replace("-", "_")
    return f"test_{stem}_{safe_type}_regression"


def _python_test_code(test_name: str, file_path: str, risk: str) -> str:
    return (
        "import pytest\n\n"
        f"def {test_name}():\n"
        f"    \"\"\"Draft regression test for {file_path}: {risk}\"\"\"\n"
        "    pytest.skip(\"Generated draft: fill in fixtures and assertions before enabling.\")\n"
    )


def _unique_test_name(base_name: str, used_names: set[str]) -> str:
    if base_name not in used_names:
        used_names.add(base_name)
        return base_name
    suffix = 2
    while f"{base_name}_{suffix}" in used_names:
        suffix += 1
    name = f"{base_name}_{suffix}"
    used_names.add(name)
    return name


def generate(
    changed_files: list[dict],
    aggregated_findings: list[dict],
    llm_findings: list[dict],
    test_impact: dict,
) -> dict:
    """Generate a structured draft test plan and draft test code snippets."""
    findings = list(aggregated_findings) + list(llm_findings)
    high_risk = [f for f in findings if f.get("severity") in {"high", "critical"}]
    test_plan: list[dict] = []
    generated_tests: list[dict] = []
    used_names: set[str] = set()

    for item in test_impact.get("new_tests_needed", []):
        file_path = item.get("file_path", "")
        test_types = item.get("suggested_test_types") or test_impact.get("recommended_test_types", ["unit"])
        risk = item.get("reason", "Changed behavior needs regression coverage.")
        for test_type in test_types:
            name = _unique_test_name(_default_test_name(file_path, test_type), used_names)
            test_plan.append({
                "name": name,
                "test_type": test_type,
                "target_file": file_path,
                "risk_covered": risk,
                "generation_status": "draft",
            })
            generated_tests.append({
                "name": name,
                "target_file": file_path,
                "test_type": test_type,
                "language": "python",
                "framework": "pytest",
                "code": _python_test_code(name, file_path, risk),
                "executed": False,
                "generation_status": "draft",
            })

    for finding in high_risk:
        file_path = finding.get("file_path") or "unknown"
        name = _unique_test_name(_default_test_name(file_path, "finding"), used_names)
        risk = finding.get("title", "High-risk finding")
        test_plan.append({
            "name": name,
            "test_type": "regression",
            "target_file": file_path,
            "risk_covered": risk,
            "source_finding_id": finding.get("id"),
            "generation_status": "draft",
        })
        generated_tests.append({
            "name": name,
            "target_file": file_path,
            "test_type": "regression",
            "language": "python",
            "framework": "pytest",
            "code": _python_test_code(name, file_path, risk),
            "executed": False,
            "source_finding_id": finding.get("id"),
            "source_finding_title": risk,
            "generation_status": "draft",
        })

    if not external_llm_enabled():
        logger.info("Test generation LLM enhancement skipped in %s mode.", llm_mode())
        logger.info("Generated %d draft test(s).", len(generated_tests))
        return {
            "test_plan": test_plan,
            "generated_tests": generated_tests,
            "notes": ["Generated tests are drafts and were not executed by the agent."],
        }

    try:
        response = call_llm(
            model=settings.llm_model,
            system_prompt=TEST_GENERATION_SYSTEM_PROMPT,
            user_prompt=redact_text(json.dumps({
                "changed_files": changed_files,
                "findings": findings,
                "test_impact": test_impact,
                "draft_result": {
                    "test_plan": test_plan,
                    "generated_tests": generated_tests,
                },
            })),
            response_format="json",
        )
        parsed = response.get("parsed_json")
        if isinstance(parsed, dict) and "test_plan" in parsed and "generated_tests" in parsed:
            parsed.setdefault("notes", [])
            parsed["notes"].append("Generated tests are drafts and were not executed by the agent.")
            return parsed
    except Exception as e:
        logger.warning("Test generation LLM enhancement skipped: %s", e)

    logger.info("Generated %d draft test(s).", len(generated_tests))
    return {
        "test_plan": test_plan,
        "generated_tests": generated_tests,
        "notes": ["Generated tests are drafts and were not executed by the agent."],
    }
