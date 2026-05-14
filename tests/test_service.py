from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CreateReviewRequest
from app.services import review_service


def test_run_review_and_save_persists_completed_report(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "reviews.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(review_service, "SessionLocal", TestingSessionLocal)

    def fake_pipeline(task_id: str, state: dict) -> dict:
        assert state["changed_files"][0]["content"] == "print('hello')"
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
            diff_text="diff --git a/app/demo.py b/app/demo.py\n+print('hello')\n",
            changed_files=[{
                "file_path": "app/demo.py",
                "language": "python",
                "content": "print('hello')",
            }],
        )
    )

    saved = review_service.run_review_and_save(task.id)

    assert saved.status == "completed"
    assert saved.current_stage == "completed"
    assert json.loads(saved.report_json)["summary"] == "ok"
    assert json.loads(saved.findings_json)[0]["title"] == "Example finding"
