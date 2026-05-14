from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ReviewTask, CreateReviewRequest

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_review(req: CreateReviewRequest) -> ReviewTask:
    db: Session = SessionLocal()
    try:
        task = ReviewTask(
            source_type=req.source_type,
            repo_name=req.repo_name,
            repo_path=req.repo_path,
            base_ref=req.base_ref,
            head_ref=req.head_ref,
            diff_text=req.diff_text,
            status="pending",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    finally:
        db.close()


def get_review(task_id: str) -> Optional[ReviewTask]:
    db: Session = SessionLocal()
    try:
        return db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
    finally:
        db.close()


def run_review_and_save(task_id: str) -> ReviewTask:
    """Run the agent pipeline for a task and persist results synchronously."""
    from app.agents.orchestrator import run_review_pipeline
    from app.models.state import ReviewState

    db: Session = SessionLocal()
    try:
        task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        task.status = "running"
        task.current_stage = "context_building"
        task.updated_at = _utcnow()
        db.commit()

        # Build changed_files from diff_text
        changed_files: list[dict] = []
        if task.diff_text:
            from app.agents.context_builder import parse_diff
            changed_files = parse_diff(task.diff_text)

        state: ReviewState = {
            "task_id": task_id,
            "status": "running",
            "source_type": task.source_type or "cli",
            "repo_path": task.repo_path,
            "repo_name": task.repo_name,
            "base_ref": task.base_ref,
            "head_ref": task.head_ref,
            "diff_text": task.diff_text or "",
            "changed_files": changed_files,
            "project_context": {},
            "static_findings": [],
            "style_findings": [],
            "security_findings": [],
            "test_impact": {},
            "aggregated_findings": [],
            "llm_findings": [],
            "test_generation_result": {},
            "validation_result": {},
            "final_report": {},
            "retry_count": {},
            "errors": [],
        }

        report_result = run_review_pipeline(task_id, state)

        # Persist results
        task.status = "completed"
        task.current_stage = "completed"
        task.findings_json = json.dumps({
            "aggregated": state.get("aggregated_findings", []),
            "llm": state.get("llm_findings", []),
        })
        task.report_json = json.dumps(report_result.get("json_report", {}))
        task.report_markdown = report_result.get("markdown_report", "")
        task.updated_at = _utcnow()
        db.commit()
        db.refresh(task)

        logger.info("Review task %s completed and saved.", task_id)
        return task
    except Exception:
        db.rollback()
        try:
            task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
            if task:
                task.status = "failed"
                task.current_stage = "failed"
                task.updated_at = _utcnow()
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
