from __future__ import annotations

import json
from types import SimpleNamespace
from datetime import datetime, timezone

from app.routers import reviews


def test_failed_report_returns_partial_report(monkeypatch) -> None:
    task = SimpleNamespace(
        id="task-1",
        status="failed",
        error_message="validation failed",
        report_markdown="# Partial report",
        report_json=json.dumps({
            "summary": "Review failed with pipeline errors.",
            "pipeline_errors": ["validation failed"],
            "generated_tests": [{"name": "draft"}],
        }),
    )
    monkeypatch.setattr(reviews, "get_review", lambda task_id: task)

    response = reviews.get_review_report("task-1")

    assert response.status == "failed"
    assert response.markdown_report == "# Partial report"
    assert response.json_report["pipeline_errors"] == ["validation failed"]
    assert response.generated_tests == [{"name": "draft"}]


def test_failed_report_without_partial_report_returns_error_payload(monkeypatch) -> None:
    task = SimpleNamespace(
        id="task-2",
        status="failed",
        error_message="orchestrator crashed",
        report_markdown=None,
        report_json=None,
    )
    monkeypatch.setattr(reviews, "get_review", lambda task_id: task)

    response = reviews.get_review_report("task-2")

    assert response.status == "failed"
    assert response.summary == "Review failed before a complete report could be generated."
    assert response.json_report["pipeline_errors"] == ["orchestrator crashed"]


def test_get_review_events_returns_task_timeline(monkeypatch) -> None:
    task = SimpleNamespace(id="task-3")
    event = SimpleNamespace(
        id="event-1",
        task_id="task-3",
        stage="static_analysis",
        status="running",
        error_message=None,
        created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(reviews, "get_review", lambda task_id: task)
    monkeypatch.setattr(reviews, "list_review_events", lambda task_id: [event])

    response = reviews.get_review_events("task-3")

    assert response[0].stage == "static_analysis"
    assert response[0].status == "running"
