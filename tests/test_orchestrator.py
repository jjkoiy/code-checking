from __future__ import annotations

from app.agents import orchestrator


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


def test_merge_changed_files_preserves_request_content_and_adds_diff_metadata() -> None:
    existing = [{"file_path": "app/demo.py", "language": "python", "content": "original content"}]
    parsed = [{
        "file_path": "app/demo.py",
        "change_type": "modified",
        "language": "python",
        "added_lines": 2,
        "deleted_lines": 1,
    }]

    merged = orchestrator._merge_changed_files(existing, parsed)

    assert merged == [{
        "file_path": "app/demo.py",
        "language": "python",
        "content": "original content",
        "change_type": "modified",
        "added_lines": 2,
        "deleted_lines": 1,
    }]


def test_review_scope_reports_raw_content_mode() -> None:
    scope = orchestrator._review_scope({
        "diff_text": "",
        "changed_files": [{
            "file_path": "app/demo.py",
            "language": "python",
            "content": "print('hello')",
        }],
    })

    assert scope["mode"] == "raw_content"
    assert scope["has_reviewable_content"] is True


def test_review_scope_reports_empty_mode() -> None:
    scope = orchestrator._review_scope({
        "diff_text": "",
        "changed_files": [],
    })

    assert scope["mode"] == "empty"
    assert scope["has_reviewable_content"] is False


def test_report_node_marks_pipeline_errors_as_failed() -> None:
    state = {
        "aggregated_findings": [],
        "llm_findings": [],
        "test_generation_result": {},
        "validation_result": {},
        "errors": [{"agent": "static_analysis", "error": "boom"}],
    }

    result = orchestrator._report_node(state)

    assert result["status"] == "failed"
    assert result["final_report"]["json_report"]["error"] == "One or more review stages failed."
    assert result["final_report"]["json_report"]["pipeline_errors"] == state["errors"]
    assert "Pipeline Errors" in result["final_report"]["markdown_report"]


def test_parallel_pipeline_runs_analysis_stages(monkeypatch) -> None:
    diff_text = (
        "diff --git a/app/demo.py b/app/demo.py\n"
        "--- a/app/demo.py\n"
        "+++ b/app/demo.py\n"
        "@@ -1 +1,2 @@\n"
        "+def handler():\n"
        "+    print('hello')\n"
    )
    monkeypatch.setattr(orchestrator.settings, "agent_execution_mode", "parallel")
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

    result = orchestrator.run_review_pipeline("task-parallel", _base_state(diff_text))

    assert result["json_report"]["metadata"]["pipeline_status"] == "completed"
    assert any(
        finding["title"] == "Print statement in production path"
        for finding in result["json_report"]["findings"]
    )


def test_pipeline_includes_rag_risk_findings_before_aggregation(monkeypatch) -> None:
    diff_text = (
        "diff --git a/app/auth.py b/app/auth.py\n"
        "--- a/app/auth.py\n"
        "+++ b/app/auth.py\n"
        "@@ -1 +1,3 @@\n"
        "+def admin_panel(request):\n"
        "+    admin = request.args.get('admin') == 'true'\n"
        "+    return admin\n"
    )
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
    monkeypatch.setattr(orchestrator.llm_review, "review", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        orchestrator.rag_risk_review,
        "review",
        lambda *args, **kwargs: [{
            "agent_name": "rag_risk_review_agent",
            "severity": "high",
            "category": "security",
            "file_path": "app/auth.py",
            "line_number": 2,
            "line_start": 2,
            "line_end": 3,
            "title": "Admin privilege is controlled by request data",
            "description": "Admin comes from a request parameter.",
            "evidence": "admin = request.args.get('admin') == 'true'",
            "suggestion": "Use authenticated server-side roles.",
            "confidence": 0.84,
            "rule_family": "weak-auth-request-param",
        }],
    )

    result = orchestrator.run_review_pipeline("task-rag", _base_state(diff_text))

    findings = result["json_report"]["findings"]
    assert any(finding.get("rule_family") == "weak-auth-request-param" for finding in findings)
    assert result["json_report"]["merge_recommendation"]["status"] == "block"
