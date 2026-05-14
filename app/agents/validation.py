"""Validation Agent for P2."""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)


def validate(generated_tests: dict, execution_logs: dict | None = None) -> dict:
    """Validate generated tests structurally and inspect execution logs when provided."""
    generated = generated_tests.get("generated_tests", []) if generated_tests else []
    errors: list[dict] = []
    validated_tests: list[dict] = []

    for test in generated:
        code = test.get("code", "")
        language = test.get("language", "python")
        result = {
            "name": test.get("name", "unnamed"),
            "syntax_valid": True,
            "executed": bool(test.get("executed")),
        }
        if language == "python" and code:
            try:
                ast.parse(code)
            except SyntaxError as exc:
                result["syntax_valid"] = False
                errors.append({
                    "test": test.get("name", "unnamed"),
                    "message": f"Python syntax error: {exc.msg}",
                    "line_number": exc.lineno,
                })
        validated_tests.append(result)

    if execution_logs:
        exit_code = execution_logs.get("exit_code")
        status = "passed" if exit_code == 0 and not errors else "failed"
        if exit_code not in (0, None):
            errors.append({
                "test": "execution",
                "message": execution_logs.get("stderr") or execution_logs.get("stdout") or "Test command failed.",
            })
    else:
        status = "not_run"

    fix_suggestions = []
    if errors:
        fix_suggestions.append("Fix generated test syntax/errors before enabling validation runs.")
    if not execution_logs:
        fix_suggestions.append("Run the generated tests in the target repository before marking validation as passed.")

    logger.info("Validation status=%s, tests=%d, errors=%d", status, len(validated_tests), len(errors))
    return {
        "status": status,
        "retry_needed": bool(errors),
        "errors": errors,
        "fix_suggestions": fix_suggestions,
        "validated_tests": validated_tests,
    }
