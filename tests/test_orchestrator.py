from __future__ import annotations

from app.agents import orchestrator


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
