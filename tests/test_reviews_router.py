from __future__ import annotations

import json
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models import CreateGitReviewRequest, CreateReviewRequest
from app.routers import reviews
from app.services.git_diff import GitDiffError


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


def test_create_review_endpoint_dispatches_task(monkeypatch) -> None:
    task = SimpleNamespace(id="task-4", status="pending")
    dispatched: dict[str, str] = {}
    monkeypatch.setattr(reviews, "create_review", lambda req: task)
    monkeypatch.setattr(
        reviews,
        "dispatch_review_task",
        lambda task_id: dispatched.setdefault("task_id", task_id),
    )

    response = reviews.create_review_endpoint(
        CreateReviewRequest(
            diff_text=(
                "diff --git a/app/demo.py b/app/demo.py\n"
                "--- a/app/demo.py\n"
                "+++ b/app/demo.py\n"
                "@@ -1 +1 @@\n"
                "+print('hello')\n"
            ),
        ),
    )

    assert response.task_id == "task-4"
    assert dispatched == {"task_id": "task-4"}


def test_create_review_endpoint_does_not_dispatch_failed_input(monkeypatch) -> None:
    task = SimpleNamespace(id="task-5", status="failed")
    monkeypatch.setattr(reviews, "create_review", lambda req: task)

    def fail_dispatch(task_id):
        raise AssertionError("failed input tasks should not be dispatched")

    monkeypatch.setattr(reviews, "dispatch_review_task", fail_dispatch)

    response = reviews.create_review_endpoint(
        CreateReviewRequest(
            source_type="github_pr",
            repo_name="owner/repo",
            pull_request_number=5,
        ),
    )

    assert response.task_id == "task-5"
    assert response.status == "failed"


def test_create_review_from_git_endpoint_dispatches_generated_diff(monkeypatch) -> None:
    task = SimpleNamespace(id="task-6", status="pending")
    created_request = {}
    dispatched: dict[str, str] = {}
    monkeypatch.setattr(
        reviews,
        "generate_diff_from_refs",
        lambda repo_path, base_ref, head_ref: (
            "diff --git a/app/demo.py b/app/demo.py\n"
            "--- a/app/demo.py\n"
            "+++ b/app/demo.py\n"
            "@@ -1 +1 @@\n"
            "+print('hello')\n"
        ),
    )

    def fake_create_review(req):
        created_request["req"] = req
        return task

    monkeypatch.setattr(reviews, "create_review", fake_create_review)
    monkeypatch.setattr(
        reviews,
        "dispatch_review_task",
        lambda task_id: dispatched.setdefault("task_id", task_id),
    )

    response = reviews.create_review_from_git_endpoint(
        CreateGitReviewRequest(
            repo_path="C:/repo/demo",
            base_ref="main",
            head_ref="feature",
        ),
    )

    req = created_request["req"]
    assert response.task_id == "task-6"
    assert dispatched == {"task_id": "task-6"}
    assert req.source_type == "local_git"
    assert req.repo_name == "demo"
    assert req.repo_path == "C:/repo/demo"
    assert req.base_ref == "main"
    assert req.head_ref == "feature"
    assert "diff --git" in req.diff_text


def test_create_review_from_git_endpoint_returns_400_on_diff_error(monkeypatch) -> None:
    monkeypatch.setattr(
        reviews,
        "generate_diff_from_refs",
        lambda repo_path, base_ref, head_ref: (_ for _ in ()).throw(GitDiffError("No reviewable diff")),
    )

    def fail_create_review(req):
        raise AssertionError("invalid git input should not create a review")

    monkeypatch.setattr(reviews, "create_review", fail_create_review)

    with pytest.raises(HTTPException) as exc:
        reviews.create_review_from_git_endpoint(
            CreateGitReviewRequest(
                repo_path="C:/repo/demo",
                base_ref="main",
                head_ref="feature",
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "No reviewable diff"
