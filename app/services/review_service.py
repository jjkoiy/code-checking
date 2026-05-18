from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ReviewTask, ReviewTaskEvent, CreateReviewRequest
from app.services.pull_request_provider import PullRequestProviderError, fetch_pull_request_review_input

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_changed_files(req: CreateReviewRequest) -> str | None:
    if not req.changed_files:
        return None
    return _serialize_changed_file_items([item.model_dump() for item in req.changed_files])


def _serialize_changed_file_items(changed_files: list[dict]) -> str | None:
    if not changed_files:
        return None
    return json.dumps(changed_files)


def _load_changed_files(task: ReviewTask) -> list[dict]:
    if not task.changed_files_json:
        return []
    try:
        loaded = json.loads(task.changed_files_json)
    except json.JSONDecodeError:
        logger.warning("Invalid changed_files_json for task=%s", task.id)
        return []
    return loaded if isinstance(loaded, list) else []


def _record_event(
    db: Session,
    task_id: str,
    stage: str,
    status: str,
    error_message: str | None = None,
) -> ReviewTaskEvent:
    event = ReviewTaskEvent(
        task_id=task_id,
        stage=stage,
        status=status,
        error_message=error_message,
    )
    db.add(event)
    return event


def create_review(req: CreateReviewRequest) -> ReviewTask:
    db: Session = SessionLocal()
    try:
        diff_text = req.diff_text
        changed_files_json = _serialize_changed_files(req)
        base_ref = req.base_ref
        head_ref = req.head_ref
        status = "pending"
        current_stage = None
        error_message = None

        if req.source_type == "github_pr":
            try:
                pr_input = fetch_pull_request_review_input(
                    req.repo_name or "",
                    req.pull_request_number or 0,
                )
                diff_text = pr_input.diff_text
                changed_files_json = _serialize_changed_file_items(pr_input.changed_files)
                base_ref = base_ref or pr_input.base_ref
                head_ref = head_ref or pr_input.head_ref
            except PullRequestProviderError as exc:
                status = "failed"
                current_stage = "input_fetch_failed"
                error_message = str(exc)

        task = ReviewTask(
            source_type=req.source_type,
            repo_name=req.repo_name,
            repo_path=req.repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            diff_text=diff_text,
            changed_files_json=changed_files_json,
            status=status,
            current_stage=current_stage,
            error_message=error_message,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        _record_event(db, task.id, current_stage or "created", status, error_message)
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


def list_review_events(task_id: str) -> list[ReviewTaskEvent]:
    db: Session = SessionLocal()
    try:
        return (
            db.query(ReviewTaskEvent)
            .filter(ReviewTaskEvent.task_id == task_id)
            .order_by(ReviewTaskEvent.created_at.asc(), ReviewTaskEvent.id.asc())
            .all()
        )
    finally:
        db.close()


def save_findings(db: Session, task: ReviewTask, findings: list[dict]) -> dict:
    """Save Agent findings for a review task."""
    task.findings_json = json.dumps(findings)
    return {"saved_count": len(findings)}


def save_report(db: Session, task: ReviewTask, markdown_report: str, json_report: dict) -> dict:
    """Save the final Markdown and JSON review report."""
    task.report_json = json.dumps(json_report)
    task.report_markdown = markdown_report
    return {"report_id": task.id, "saved": True}


def _latest_pipeline_error(state: dict) -> str | None:
    errors = state.get("errors") or []
    if not errors:
        return None
    latest = errors[-1]
    if isinstance(latest, dict):
        agent = latest.get("agent", "unknown")
        error = latest.get("error", "")
        return f"{agent}: {error}" if error else str(latest)
    return str(latest)


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
        _record_event(db, task_id, "context_building", "running")
        db.commit()

        # Build changed_files from persisted request data, falling back to diff parsing.
        changed_files: list[dict] = _load_changed_files(task)
        if task.diff_text:
            from app.agents.context_builder import parse_diff
            changed_files = changed_files or parse_diff(task.diff_text)

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
            "llm_mode": "mock",
            "test_generation_result": {},
            "validation_result": {},
            "validation_warnings": [],
            "final_report": {},
            "retry_count": {},
            "errors": [],
        }

        def persist_stage(stage: str, stage_state: ReviewState) -> None:
            task.current_stage = stage
            latest_error = _latest_pipeline_error(stage_state)
            if latest_error:
                task.error_message = latest_error
            task.updated_at = _utcnow()
            _record_event(
                db,
                task_id,
                stage,
                stage_state.get("status", task.status),
                latest_error,
            )
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("Failed to persist stage=%s for task=%s: %s", stage, task_id, exc)

        report_result = run_review_pipeline(
            task_id,
            state,
            on_stage_start=persist_stage,
            on_stage_end=persist_stage,
        )
        json_report = report_result.get("json_report", {})
        pipeline_error = json_report.get("error") if isinstance(json_report, dict) else None

        # Persist results
        task.status = "failed" if pipeline_error else "completed"
        task.current_stage = "failed" if pipeline_error else "completed"
        task.error_message = str(pipeline_error) if pipeline_error else None
        findings = json_report.get("findings", []) if isinstance(json_report, dict) else []
        save_findings(db, task, findings)
        save_report(db, task, report_result.get("markdown_report", ""), json_report)
        task.updated_at = _utcnow()
        _record_event(db, task_id, task.current_stage, task.status, task.error_message)
        db.commit()
        db.refresh(task)

        logger.info("Review task %s finished with status=%s and saved.", task_id, task.status)
        return task
    except Exception:
        db.rollback()
        try:
            task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
            if task:
                task.status = "failed"
                task.current_stage = "failed"
                task.error_message = "Review pipeline failed; check server logs for details."
                task.updated_at = _utcnow()
                _record_event(db, task_id, "failed", "failed", task.error_message)
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
