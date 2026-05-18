from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CreateReviewRequest
from app.services.pull_request_provider import PullRequestProviderError, PullRequestReviewInput
from app.services import review_service


def test_run_review_and_save_persists_completed_report(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "reviews.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(review_service, "SessionLocal", TestingSessionLocal)

    def fake_pipeline(task_id: str, state: dict, **kwargs) -> dict:
        assert state["changed_files"][0]["content"] == "print('hello')"
        on_stage_start = kwargs.get("on_stage_start")
        if on_stage_start:
            on_stage_start("static_analysis", state)
            check_db = TestingSessionLocal()
            try:
                saved_task = check_db.query(review_service.ReviewTask).filter_by(id=task_id).first()
                assert saved_task.current_stage == "static_analysis"
            finally:
                check_db.close()
        return {
            "markdown_report": "# OK",
            "json_report": {
                "summary": "ok",
                "findings": [{
                    "title": "Example finding",
                    "severity": "low",
                    "category": "style",
                }],
                "generated_tests": [],
            },
        }

    import app.agents.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "run_review_pipeline", fake_pipeline)

    task = review_service.create_review(
        CreateReviewRequest(
            diff_text=(
                "diff --git a/app/demo.py b/app/demo.py\n"
                "--- a/app/demo.py\n"
                "+++ b/app/demo.py\n"
                "@@ -1 +1 @@\n"
                "+print('hello')\n"
            ),
            changed_files=[{
                "file_path": "app/demo.py",
                "language": "python",
                "content": "print('hello')",
            }],
        )
    )

    saved = review_service.run_review_and_save(task.id)
    events = review_service.list_review_events(task.id)

    assert saved.status == "completed"
    assert saved.current_stage == "completed"
    assert json.loads(saved.report_json)["summary"] == "ok"
    assert json.loads(saved.findings_json)[0]["title"] == "Example finding"
    assert events[0].stage == "created"
    assert any(event.stage == "static_analysis" for event in events)
    assert events[-1].status == "completed"


def test_create_review_loads_github_pr_input(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "reviews.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(review_service, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        review_service,
        "fetch_pull_request_review_input",
        lambda repo, number: PullRequestReviewInput(
            diff_text=(
                "diff --git a/app/demo.py b/app/demo.py\n"
                "--- a/app/demo.py\n"
                "+++ b/app/demo.py\n"
                "@@ -1 +1 @@\n"
                "+print('hello')\n"
            ),
            changed_files=[{"file_path": "app/demo.py", "language": "python"}],
            base_ref="main",
            head_ref="feature",
        ),
    )

    task = review_service.create_review(
        CreateReviewRequest(
            source_type="github_pr",
            repo_name="owner/repo",
            pull_request_number=7,
        )
    )

    assert task.status == "pending"
    assert task.base_ref == "main"
    assert task.head_ref == "feature"
    assert "diff --git" in task.diff_text
    assert json.loads(task.changed_files_json)[0]["file_path"] == "app/demo.py"


def test_create_review_records_failed_github_pr_input(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "reviews.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(review_service, "SessionLocal", TestingSessionLocal)

    def fail_fetch(repo: str, number: int) -> PullRequestReviewInput:
        raise PullRequestProviderError("gh auth failed")

    monkeypatch.setattr(review_service, "fetch_pull_request_review_input", fail_fetch)

    task = review_service.create_review(
        CreateReviewRequest(
            source_type="github_pr",
            repo_name="owner/repo",
            pull_request_number=7,
        )
    )
    events = review_service.list_review_events(task.id)

    assert task.status == "failed"
    assert task.current_stage == "input_fetch_failed"
    assert task.error_message == "gh auth failed"
    assert events[-1].error_message == "gh auth failed"
