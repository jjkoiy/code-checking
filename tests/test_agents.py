from __future__ import annotations

from app.agents import (
    finding_aggregator,
    llm_review,
    report,
    security_scan,
    static_analysis,
    style_check,
    test_generation,
    test_impact,
)
from app.agents.diff_utils import iter_added_lines


def test_diff_utils_maps_added_lines_to_new_file_lines(risky_python_diff: str) -> None:
    added = list(iter_added_lines(risky_python_diff))

    assert added[0] == (
        "app/demo.py",
        2,
        "    query = f\"SELECT * FROM users WHERE name = '{user}'\"",
    )
    assert added[-1] == ("app/demo.py", 6, "    except Exception:")


def test_static_security_and_style_findings_include_file_and_line(risky_python_diff: str) -> None:
    changed_files = [{"file_path": "app/demo.py", "language": "python"}]

    static_findings = static_analysis.analyze(risky_python_diff, changed_files)
    security_findings = security_scan.scan(risky_python_diff, changed_files)
    style_findings = style_check.check(changed_files, risky_python_diff)

    assert any(
        finding["title"] == "SQL string concatenation / interpolation"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 2
        for finding in static_findings
    )
    assert any(
        finding["title"] == "Potential SQL injection via f-string"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 2
        for finding in security_findings
    )
    assert style_findings == [
        {
            "agent_name": "style_agent",
            "severity": "low",
            "category": "maintainability",
            "file_path": "app/demo.py",
            "line_number": 3,
            "title": "TODO/FIXME left in code",
            "description": "Unresolved TODO or FIXME comment may indicate incomplete work.",
            "evidence": "# TODO tighten auth",
            "suggestion": "Address the item or convert it to a tracked ticket.",
            "confidence": 0.60,
        }
    ]


def test_static_security_and_style_scan_changed_file_content_without_diff() -> None:
    changed_files = [
        {
            "file_path": "app/demo.py",
            "language": "python",
            "content": "\n".join([
                "def handler(user):",
                "    # TODO tighten auth",
                "    query = f\"SELECT * FROM users WHERE name = '{user}'\"",
                "    return query",
            ]),
        }
    ]

    static_findings = static_analysis.analyze("", changed_files)
    security_findings = security_scan.scan("", changed_files)
    style_findings = style_check.check(changed_files, "")

    assert any(
        finding["title"] == "SQL string concatenation / interpolation"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 3
        for finding in static_findings
    )
    assert any(
        finding["title"] == "Potential SQL injection via f-string"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 3
        for finding in security_findings
    )
    assert any(
        finding["title"] == "TODO/FIXME left in code"
        and finding["line_number"] == 2
        for finding in style_findings
    )


def test_llm_review_uses_local_mock_when_provider_is_mock(monkeypatch, risky_python_diff: str) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")

    findings = llm_review.review(
        diff_text=risky_python_diff,
        changed_files=[{"file_path": "app/auth.py", "language": "python"}],
        aggregated_findings=[],
        project_context={"languages": ["python"], "risk_hints": ["auth"]},
    )

    assert findings
    assert any(finding["agent_name"] == "llm_review_agent" for finding in findings)
    assert all(finding["file_path"] for finding in findings)
    assert all(finding["line_number"] is not None for finding in findings)
    assert all(finding["evidence"] for finding in findings)


def test_llm_review_uses_mock_when_external_llm_is_disabled(monkeypatch, risky_python_diff: str) -> None:
    def fail_call_llm(*args, **kwargs):
        raise AssertionError("call_llm should not be called when external LLM is disabled")

    monkeypatch.setattr(llm_review.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_review.settings, "llm_model", "deepseek-chat")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_review.settings, "llm_external_enabled", False)
    monkeypatch.setattr(llm_review, "call_llm", fail_call_llm)

    findings = llm_review.review(
        diff_text=risky_python_diff,
        changed_files=[{"file_path": "app/auth.py", "language": "python"}],
        aggregated_findings=[],
        project_context={"languages": ["python"], "risk_hints": ["auth"]},
    )

    assert findings
    assert all(finding["agent_name"] == "llm_review_agent" for finding in findings)


def test_test_generation_skips_call_llm_when_external_llm_is_disabled(monkeypatch) -> None:
    def fail_call_llm(*args, **kwargs):
        raise AssertionError("call_llm should not be called when external LLM is disabled")

    monkeypatch.setattr(test_generation.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(test_generation.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(test_generation.settings, "llm_external_enabled", False)
    monkeypatch.setattr(test_generation, "call_llm", fail_call_llm)

    result = test_generation.generate(
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[],
        llm_findings=[],
        test_impact={
            "new_tests_needed": [{
                "file_path": "app/demo.py",
                "suggested_test_types": ["unit"],
                "reason": "Changed behavior needs regression coverage.",
            }],
        },
    )

    assert result["generated_tests"]
    assert result["generated_tests"][0]["executed"] is False


def test_test_generation_creates_draft_for_each_high_risk_finding(monkeypatch) -> None:
    monkeypatch.setattr(test_generation.settings, "llm_provider", "mock")
    monkeypatch.setattr(test_generation.settings, "llm_api_key", "")

    result = test_generation.generate(
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[
            {
                "id": "finding-1",
                "agent_name": "security_agent",
                "severity": "critical",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 3,
                "title": "Potential command injection",
                "description": "shell=True is dangerous.",
                "confidence": 0.9,
            },
            {
                "id": "finding-2",
                "agent_name": "static_analysis_agent",
                "severity": "high",
                "category": "bug",
                "file_path": "app/demo.py",
                "line_number": 4,
                "title": "High-risk regression",
                "description": "Important behavior changed.",
                "confidence": 0.8,
            },
        ],
        llm_findings=[],
        test_impact={},
    )

    finding_drafts = [
        test for test in result["generated_tests"]
        if test.get("source_finding_id") in {"finding-1", "finding-2"}
    ]
    assert len(finding_drafts) == 2
    assert all(test["generation_status"] == "draft" for test in finding_drafts)


def test_llm_review_redacts_sensitive_values_before_external_call(monkeypatch) -> None:
    captured = {}

    def fake_call_llm(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return {"parsed_json": {"findings": []}, "content": "{}", "usage": {}}

    monkeypatch.setattr(llm_review.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_review.settings, "llm_model", "deepseek-chat")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_review.settings, "llm_external_enabled", True)
    monkeypatch.setattr(llm_review.settings, "llm_redaction_enabled", True)
    monkeypatch.setattr(llm_review, "call_llm", fake_call_llm)

    llm_review.review(
        diff_text="""diff --git a/app/demo.py b/app/demo.py
--- a/app/demo.py
+++ b/app/demo.py
@@ -1 +1,3 @@
+API_KEY = "fake-secret-value"
+password = "hunter2"
+def login(user): return user
""",
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[],
        project_context={"languages": ["python"]},
    )

    assert "fake-secret-value" not in captured["user_prompt"]
    assert "hunter2" not in captured["user_prompt"]
    assert "[REDACTED_SECRET]" in captured["user_prompt"]


def test_plain_text_input_does_not_trigger_mock_llm_findings(monkeypatch) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")

    findings = llm_review.review(
        diff_text="please review this api input json and login idea",
        changed_files=[],
        aggregated_findings=[],
        project_context={"languages": [], "risk_hints": ["api", "input", "login"]},
    )

    assert findings == []


def test_non_code_diff_does_not_trigger_code_findings(monkeypatch) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")
    docs_diff = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1,1 +1,4 @@
 Project notes
+TODO: describe api input json
+password = "not-a-real-secret"
+login flow explanation
"""
    changed_files = [{"file_path": "README.md", "language": "markdown"}]

    assert static_analysis.analyze(docs_diff, changed_files) == []
    assert security_scan.scan(docs_diff, changed_files) == []
    assert style_check.check(changed_files, docs_diff) == []
    assert llm_review.review(docs_diff, changed_files, [], {"languages": ["markdown"]}) == []


def test_raw_code_snippet_with_file_heading_triggers_findings(monkeypatch) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")
    raw_code = """# app/demo.py

def handler(user):
    query = f"SELECT * FROM users WHERE name = '{user}'"
    # TODO tighten auth

    try:
        execute_sql(query)
    except Exception:
        pass
"""
    changed_files: list[dict] = []

    static_findings = static_analysis.analyze(raw_code, changed_files)
    security_findings = security_scan.scan(raw_code, changed_files)
    style_findings = style_check.check(changed_files, raw_code)
    llm_findings = llm_review.review(
        raw_code,
        changed_files,
        [],
        {"languages": ["python"], "risk_hints": ["auth"]},
    )

    assert any(finding["title"] == "SQL string concatenation / interpolation" for finding in static_findings)
    assert any(finding["title"] == "Potential SQL injection via f-string" for finding in security_findings)
    assert any(finding["title"] == "TODO/FIXME left in code" for finding in style_findings)
    assert llm_findings


def test_test_impact_keeps_per_file_suggested_types_independent(monkeypatch) -> None:
    monkeypatch.setattr(test_impact, "vector_search", lambda *args, **kwargs: {"documents": []})

    result = test_impact.analyze(
        changed_files=[
            {"file_path": "app/routers/reviews.py", "language": "python"},
            {"file_path": "README.md", "language": "markdown"},
        ],
        diff_text="diff --git a/README.md b/README.md\n+Documentation only\n",
    )

    by_file = {item["file_path"]: item for item in result["new_tests_needed"]}
    assert by_file["app/routers/reviews.py"]["suggested_test_types"] == ["integration", "unit"]
    assert "README.md" not in by_file


def test_test_impact_skips_non_code_files(monkeypatch) -> None:
    monkeypatch.setattr(test_impact, "vector_search", lambda *args, **kwargs: {"documents": []})

    result = test_impact.analyze(
        changed_files=[{"file_path": "README.md", "language": "markdown"}],
        diff_text="diff --git a/README.md b/README.md\n+Document the api login flow\n",
    )

    assert result["recommended_test_types"] == []
    assert result["new_tests_needed"] == []
    assert result["existing_tests_to_run"] == []


def test_security_scan_does_not_flag_subprocess_without_shell_true() -> None:
    raw_code = """# app/demo.py

import subprocess

def list_path(path):
    return subprocess.run(["ls", path], check=False)
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/demo.py", "language": "python"}],
    )

    assert not any(finding["title"] == "Potential command injection" for finding in findings)


def test_security_scan_flags_subprocess_shell_true() -> None:
    raw_code = """# app/demo.py

import subprocess

def run_command(command):
    return subprocess.run(command, shell=True)
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/demo.py", "language": "python"}],
    )

    assert any(finding["title"] == "Potential command injection" for finding in findings)


def test_security_scan_allows_yaml_safe_load() -> None:
    raw_code = """# app/demo.py

import yaml

def load_config(raw):
    return yaml.safe_load(raw)
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/demo.py", "language": "python"}],
    )

    assert not any(finding["title"] == "Insecure deserialization" for finding in findings)


def test_report_uses_plain_ok_text_for_empty_review() -> None:
    result = report.generate([], [], {}, {})

    assert "[OK] No issues found in this review." in result["markdown_report"]
    assert result["json_report"]["llm_mode"] == "mock"


def test_report_includes_metadata_and_review_scope() -> None:
    result = report.generate(
        [],
        [],
        {},
        {},
        metadata={
            "agent_count": 10,
            "duration_seconds": 0.12,
            "llm_mode": "mock",
            "pipeline_status": "completed",
        },
        review_scope={
            "file_count": 2,
            "languages": ["python"],
            "mode": "added_lines_only",
            "added_lines": 7,
            "has_reviewable_content": True,
        },
    )

    assert result["json_report"]["metadata"]["agent_count"] == 10
    assert result["json_report"]["review_scope"]["file_count"] == 2
    assert "## Review Scope" in result["markdown_report"]


def test_report_distinguishes_no_reviewable_content() -> None:
    result = report.generate(
        [],
        [],
        {},
        {},
        review_scope={
            "file_count": 0,
            "languages": [],
            "mode": "added_lines_only",
            "added_lines": 0,
            "has_reviewable_content": False,
        },
    )

    assert "[WARN] No reviewable content was available" in result["markdown_report"]


def test_report_severity_counts_exclude_blocking_findings() -> None:
    result = report.generate(
        aggregated_findings=[
            {
                "severity": "high",
                "blocking": True,
                "title": "Blocking high",
                "category": "security",
                "confidence": 0.9,
            },
            {
                "severity": "high",
                "blocking": False,
                "title": "Non-blocking high",
                "category": "security",
                "confidence": 0.8,
            },
        ],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
    )

    assert "1 blocking; non-blocking severity: 0 critical, 1 high" in result["summary"]
    assert result["json_report"]["blocking_count"] == 1
    assert result["json_report"]["high_count"] == 1
    assert result["json_report"]["merge_recommendation"]["status"] == "block"
    assert "## Merge Recommendation" in result["markdown_report"]
    assert "## High-Risk Summary" in result["markdown_report"]


def test_report_merge_recommendation_allows_clean_review() -> None:
    result = report.generate(
        aggregated_findings=[],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
    )

    assert result["json_report"]["merge_recommendation"]["status"] == "pass"


def test_report_merge_recommendation_flags_medium_risk_as_caution() -> None:
    result = report.generate(
        aggregated_findings=[
            {
                "severity": "medium",
                "blocking": False,
                "title": "Regression coverage gap",
                "category": "reliability",
                "confidence": 0.7,
            },
        ],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
    )

    assert result["json_report"]["merge_recommendation"]["status"] == "caution"


def test_finding_aggregator_normalizes_and_drops_invalid_findings() -> None:
    warnings: list[dict] = []

    result = finding_aggregator.aggregate(
        [
            {
                "agent_name": "llm_review_agent",
                "severity": "HIGH",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 2,
                "title": "Potential injection",
                "description": "User input reaches a query.",
                "evidence": "query = f'SELECT {user}'",
                "suggestion": "Use parameters.",
                "confidence": "0.9",
            },
            {
                "agent_name": "llm_review_agent",
                "severity": "severe",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 3,
                "title": "Bad severity",
                "description": "This should be dropped.",
                "confidence": 0.9,
            },
            {
                "agent_name": "llm_review_agent",
                "severity": "medium",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 4,
                "description": "Missing title should be dropped.",
                "confidence": 0.8,
            },
        ],
        validation_warnings=warnings,
    )

    assert len(result) == 1
    assert result[0]["severity"] == "high"
    assert result[0]["confidence"] == 0.9
    assert result[0]["blocking"] is True
    assert len(warnings) == 2


def test_report_consumes_only_final_normalized_findings() -> None:
    result = report.generate(
        aggregated_findings=[],
        llm_findings=[
            {
                "agent_name": "llm_review_agent",
                "severity": "critical",
                "category": "security",
                "title": "Raw LLM finding",
                "description": "This raw output was not normalized.",
                "confidence": 1.0,
            }
        ],
        test_generation_result={},
        validation_result={},
    )

    assert result["json_report"]["total_findings"] == 0
    assert "Raw LLM finding" not in result["markdown_report"]
