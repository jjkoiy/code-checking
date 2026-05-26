from __future__ import annotations

import re

from app.agents import finding_aggregator, orchestrator


QUALITY_DIMENSIONS = (
    "finding_correctness",
    "severity_accuracy",
    "evidence_quality",
    "actionability",
    "dedup_quality",
    "report_consistency",
)

FAILURE_AREAS = {
    "finding_correctness": "agent",
    "evidence_quality": "agent",
    "actionability": "agent",
    "severity_accuracy": "aggregator",
    "dedup_quality": "aggregator",
    "report_consistency": "report",
}


def _base_state(diff_text: str) -> dict:
    return {
        "status": "running",
        "source_type": "cli",
        "repo_path": None,
        "repo_name": None,
        "base_ref": None,
        "head_ref": None,
        "diff_text": diff_text,
        "changed_files": [],
        "project_context": {},
        "static_findings": [],
        "style_findings": [],
        "security_findings": [],
        "test_impact": {},
        "aggregated_findings": [],
        "llm_findings": [],
        "llm_mode": "mock",
        "test_generation_result": {},
        "validation_result": {},
        "validation_warnings": [],
        "final_report": {},
        "retry_count": {},
        "errors": [],
    }


def _run_pipeline(monkeypatch, diff_text: str) -> dict:
    monkeypatch.setattr(orchestrator.settings, "agent_execution_mode", "sequential")
    monkeypatch.setattr(
        orchestrator.context_builder,
        "vector_search",
        lambda collection, query, top_k=3: {"documents": []},
    )
    monkeypatch.setattr(
        orchestrator.test_impact,
        "vector_search",
        lambda collection, query, top_k=3: {"documents": []},
    )
    monkeypatch.setattr(orchestrator.llm_review, "external_llm_enabled", lambda: False)
    return orchestrator.run_review_pipeline(
        "quality-calibration",
        _base_state(diff_text),
    )


def _quality_score(result: dict) -> dict[str, bool]:
    json_report = result["json_report"]
    findings = json_report.get("findings", [])
    severity_counts = {
        "critical": json_report.get("critical_count", 0),
        "high": json_report.get("high_count", 0),
        "medium": json_report.get("medium_count", 0),
        "low": json_report.get("low_count", 0),
    }
    actual_counts = {
        severity: sum(
            1
            for finding in findings
            if finding.get("severity") == severity
        )
        for severity in severity_counts
    }
    duplicate_locations = {
        (
            finding.get("file_path"),
            finding.get("line_start") or finding.get("line_number"),
            finding.get("line_end") or finding.get("line_number"),
            finding.get("rule_family")
            or re.sub(r"\W+", " ", finding.get("title", "").lower()).strip(),
        )
        for finding in findings
    }
    recommendation = json_report.get("merge_recommendation", {})

    return {
        "finding_correctness": bool(findings) or json_report.get("total_findings") == 0,
        "severity_accuracy": (
            actual_counts == severity_counts
            and json_report.get("blocking_count", 0)
            == sum(1 for finding in findings if finding.get("blocking"))
            and (
                recommendation.get("status") == "block"
                if json_report.get("blocking_count", 0)
                else recommendation.get("status") in {"pass", "caution", "needs_review"}
            )
        ),
        "evidence_quality": all(
            finding.get("file_path")
            and finding.get("line_number") is not None
            and finding.get("evidence")
            for finding in findings
        ),
        "actionability": all(finding.get("suggestion") for finding in findings),
        "dedup_quality": len(duplicate_locations) == len(findings),
        "report_consistency": (
            json_report.get("total_findings") == len(findings)
            and result["summary"] == json_report.get("summary")
            and str(json_report.get("total_findings")) in result["markdown_report"]
            and "\ufffd" not in result["markdown_report"]
            and "\u0431\u043a" not in result["markdown_report"]
        ),
    }


def _assert_quality(result: dict, *dimensions: str) -> None:
    score = _quality_score(result)
    missing = set(dimensions) - set(QUALITY_DIMENSIONS)
    assert not missing, f"Unknown quality dimension(s): {sorted(missing)}"
    failed = {
        dimension: FAILURE_AREAS[dimension]
        for dimension in dimensions
        if not score[dimension]
    }
    assert not failed


def test_report_quality_blocks_sql_injection_with_actionable_evidence(monkeypatch) -> None:
    diff_text = """diff --git a/app/user_service.py b/app/user_service.py
index 1111111..2222222 100644
--- a/app/user_service.py
+++ b/app/user_service.py
@@ -1,2 +1,4 @@
 def find_user(name):
+    query = f"SELECT * FROM users WHERE name = '{name}'"
+    return db.execute(query)
"""

    result = _run_pipeline(monkeypatch, diff_text)
    report = result["json_report"]
    sql_findings = [
        finding
        for finding in report["findings"]
        if "sql injection" in (
            finding.get("title", "") + " " + finding.get("description", "")
        ).lower()
    ]

    assert report["merge_recommendation"]["status"] == "block"
    assert sql_findings
    assert sql_findings[0]["severity"] == "critical"
    assert sql_findings[0]["blocking"] is True
    assert sql_findings[0]["file_path"] == "app/user_service.py"
    assert sql_findings[0]["line_number"] == 2
    assert "parameterized" in sql_findings[0]["suggestion"].lower()
    _assert_quality(
        result,
        "finding_correctness",
        "severity_accuracy",
        "evidence_quality",
        "actionability",
        "report_consistency",
    )


def test_report_quality_keeps_print_as_low_non_blocking(monkeypatch) -> None:
    diff_text = """diff --git a/app/demo.py b/app/demo.py
index 1111111..2222222 100644
--- a/app/demo.py
+++ b/app/demo.py
@@ -1 +1,3 @@
 def handler():
+    print("debug")
+    return "ok"
"""

    result = _run_pipeline(monkeypatch, diff_text)
    report = result["json_report"]
    print_findings = [
        finding
        for finding in report["findings"]
        if finding.get("title") == "Print statement in production path"
    ]

    assert print_findings
    assert print_findings[0]["severity"] == "low"
    assert print_findings[0]["blocking"] is False
    assert report["merge_recommendation"]["status"] == "pass"
    _assert_quality(
        result,
        "finding_correctness",
        "severity_accuracy",
        "evidence_quality",
        "actionability",
        "report_consistency",
    )


def test_report_quality_does_not_flag_safe_subprocess_as_command_injection(monkeypatch) -> None:
    diff_text = """diff --git a/app/commands.py b/app/commands.py
index 1111111..2222222 100644
--- a/app/commands.py
+++ b/app/commands.py
@@ -1 +1,4 @@
+import subprocess
+
 def echo_name(name):
+    return subprocess.run(["echo", name], shell=False, check=True)
"""

    result = _run_pipeline(monkeypatch, diff_text)
    report = result["json_report"]

    assert not any(
        "command injection" in (
            finding.get("title", "") + " " + finding.get("description", "")
        ).lower()
        for finding in report["findings"]
    )
    assert report["merge_recommendation"]["status"] == "pass"
    _assert_quality(result, "finding_correctness", "severity_accuracy", "report_consistency")


def test_report_quality_treats_empty_input_as_caution_not_clean_pass(monkeypatch) -> None:
    result = _run_pipeline(monkeypatch, "")
    report = result["json_report"]

    assert report["review_scope"]["has_reviewable_content"] is False
    assert report["merge_recommendation"]["status"] == "caution"
    assert report["merge_recommendation"]["label"] == "No reviewable content"
    assert "No reviewable content was available" in result["markdown_report"]
    _assert_quality(result, "finding_correctness", "severity_accuracy", "report_consistency")


def test_report_quality_merges_empty_broad_exception(monkeypatch) -> None:
    diff_text = """diff --git a/app/worker.py b/app/worker.py
index 1111111..2222222 100644
--- a/app/worker.py
+++ b/app/worker.py
@@ -1 +1,5 @@
+def handle():
+    try:
+        risky()
+    except Exception:
+        pass
"""

    result = _run_pipeline(monkeypatch, diff_text)
    findings = result["json_report"]["findings"]
    exception_findings = [
        finding for finding in findings
        if finding.get("rule_family") == "exception-handling"
    ]

    assert len(exception_findings) == 1
    assert exception_findings[0]["title"] == "Overly broad exception catch with empty handling"
    assert exception_findings[0]["severity"] == "medium"
    assert "except Exception:\n        pass" in exception_findings[0]["evidence"]
    _assert_quality(result, "dedup_quality", "evidence_quality", "report_consistency")


def test_report_quality_recognizes_auth_todo_as_security_caution(monkeypatch) -> None:
    diff_text = """diff --git a/app/auth.py b/app/auth.py
index 1111111..2222222 100644
--- a/app/auth.py
+++ b/app/auth.py
@@ -1 +1,3 @@
+def check_user(request):
+    # TODO tighten auth
+    return True
"""

    result = _run_pipeline(monkeypatch, diff_text)
    auth_findings = [
        finding for finding in result["json_report"]["findings"]
        if finding.get("rule_family") == "auth-todo"
    ]

    assert auth_findings
    assert auth_findings[0]["category"] == "security"
    assert auth_findings[0]["severity"] == "medium"
    assert result["json_report"]["merge_recommendation"]["status"] == "caution"
    suggestions = "\n".join(
        item.get("assertion_direction", "")
        for item in result["json_report"]["test_suggestions"]
    )
    assert "unauthenticated" in suggestions
    assert "insufficient-permission" in suggestions


def test_report_quality_marks_low_context_findings_for_human_confirmation() -> None:
    from app.agents import report

    result = report.generate(
        aggregated_findings=[
            {
                "agent_name": "llm_review_agent",
                "severity": "low",
                "category": "security",
                "file_path": "app/integration.py",
                "line_number": 12,
                "title": "External callback behavior needs context",
                "description": "The changed callback may depend on deployment-specific policy.",
                "evidence": "callback(url)",
                "suggestion": "Confirm the expected callback trust boundary with the service owner.",
                "confidence": 0.45,
                "blocking": False,
                "certainty": "needs_context",
            }
        ],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
    )

    assert "Needs human confirmation" in result["markdown_report"]
    assert "vulnerability" not in result["markdown_report"].lower()


def test_report_quality_deduplicates_same_sql_risk_across_agents() -> None:
    findings = finding_aggregator.aggregate(
        [
            {
                "agent_name": "static_analysis_agent",
                "severity": "high",
                "category": "bug",
                "file_path": "app/demo.py",
                "line_number": 7,
                "title": "SQL string concatenation / interpolation",
                "description": "SQL query built with f-string interpolation is prone to SQL injection.",
                "evidence": "query = f\"SELECT * FROM users WHERE name = '{name}'\"",
                "suggestion": "Use parameterized queries.",
                "confidence": 0.75,
            },
            {
                "agent_name": "security_agent",
                "severity": "critical",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 7,
                "title": "Potential SQL injection via f-string",
                "description": "SQL query built with f-string interpolation allows SQL injection attacks.",
                "evidence": "query = f\"SELECT * FROM users WHERE name = '{name}'\"",
                "suggestion": "Use parameterized queries or an ORM.",
                "confidence": 0.80,
            },
            {
                "agent_name": "llm_review_agent",
                "severity": "high",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 7,
                "title": "SQL injection risk needs review",
                "description": "The SQL query uses string interpolation with untrusted input.",
                "evidence": "query = f\"SELECT * FROM users WHERE name = '{name}'\"",
                "suggestion": "Use a parameterized query and add a regression test.",
                "confidence": 0.78,
            },
        ]
    )

    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    assert findings[0]["blocking"] is True
    assert findings[0]["source_agents"] == [
        "static_analysis_agent",
        "security_agent",
        "llm_review_agent",
    ]
