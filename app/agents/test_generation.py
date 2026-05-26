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


def _finding_family(finding: dict) -> str:
    text = " ".join(
        str(finding.get(field, "")).lower()
        for field in ("rule_family", "title", "description", "suggestion")
    )
    if "sql" in text and ("injection" in text or "parameter" in text):
        return "sql-injection"
    if "exception" in text or "except" in text or "silently" in text:
        return "exception-handling"
    if "auth" in text or "permission" in text or "unauthorized" in text:
        return "auth-todo"
    return finding.get("rule_family") or "finding"


def _test_strategy_for_finding(finding: dict) -> dict:
    family = _finding_family(finding)
    if family == "sql-injection":
        return {
            "test_type": "security",
            "risk_covered": "SQL injection regression: verify payloads cannot alter query semantics and SQL uses bound parameters.",
            "assertion_direction": "Use a payload such as \"' OR '1'='1\" and assert the data access layer passes values as parameters, not string-built SQL.",
        }
    if family == "exception-handling":
        return {
            "test_type": "unit",
            "risk_covered": "Exception handling regression: verify the error path is observable and not silently swallowed.",
            "assertion_direction": "Mock the failing dependency, assert useful logging or explicit error handling, and assert unexpected errors are not hidden.",
        }
    if family == "auth-todo":
        return {
            "test_type": "integration",
            "risk_covered": "auth/security TODO regression: verify unauthenticated and unauthorized requests are rejected.",
            "assertion_direction": "Add unauthenticated and insufficient-permission cases and assert 401/403 or the project-specific denial response.",
        }
    return {
        "test_type": "regression",
        "risk_covered": finding.get("title", "Changed behavior needs regression coverage."),
        "assertion_direction": "Assert the expected behavior around the changed line and cover the failure mode named by the finding.",
    }


def _python_test_code(test_name: str, file_path: str, risk: str, assertion_direction: str) -> str:
    return (
        f"def {test_name}():\n"
        f"    \"\"\"Draft regression test for {file_path}: {risk}\"\"\"\n"
        f"    # TODO: arrange fixtures and inputs for `{file_path}`.\n"
        f"    # Assertion direction: {assertion_direction}\n"
        "    assert False, \"TODO: implement the regression assertion described above\"\n"
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
    targeted_findings = [
        finding for finding in findings
        if finding.get("rule_family") in {"sql-injection", "exception-handling", "auth-todo"}
        or finding.get("severity") in {"high", "critical"}
    ]
    test_plan: list[dict] = []
    generated_tests: list[dict] = []
    used_names: set[str] = set()
    covered_files = {finding.get("file_path") for finding in targeted_findings if finding.get("file_path")}

    for item in test_impact.get("new_tests_needed", []):
        file_path = item.get("file_path", "")
        if file_path in covered_files:
            continue
        test_types = item.get("suggested_test_types") or test_impact.get("recommended_test_types", ["unit"])
        risk = item.get("reason", "Changed behavior needs regression coverage.")
        assertion_direction = "Assert the changed behavior directly, including the most likely failure path."
        for test_type in test_types:
            name = _unique_test_name(_default_test_name(file_path, test_type), used_names)
            test_plan.append({
                "name": name,
                "test_type": test_type,
                "target_file": file_path,
                "risk_covered": risk,
                "assertion_direction": assertion_direction,
                "generation_status": "draft",
            })
            generated_tests.append({
                "name": name,
                "target_file": file_path,
                "test_type": test_type,
                "language": "python",
                "framework": "pytest",
                "code": _python_test_code(name, file_path, risk, assertion_direction),
                "executed": False,
                "generation_status": "draft",
            })

    for finding in targeted_findings:
        file_path = finding.get("file_path") or "unknown"
        strategy = _test_strategy_for_finding(finding)
        name = _unique_test_name(_default_test_name(file_path, strategy["test_type"]), used_names)
        test_plan.append({
            "name": name,
            "test_type": strategy["test_type"],
            "target_file": file_path,
            "risk_covered": strategy["risk_covered"],
            "assertion_direction": strategy["assertion_direction"],
            "source_finding_id": finding.get("id"),
            "generation_status": "draft",
        })
        generated_tests.append({
            "name": name,
            "target_file": file_path,
            "test_type": strategy["test_type"],
            "language": "python",
            "framework": "pytest",
            "code": _python_test_code(
                name,
                file_path,
                strategy["risk_covered"],
                strategy["assertion_direction"],
            ),
            "executed": False,
            "source_finding_id": finding.get("id"),
            "source_finding_title": finding.get("title", "Finding"),
            "assertion_direction": strategy["assertion_direction"],
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
