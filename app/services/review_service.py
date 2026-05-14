from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ReviewTask, CreateReviewRequest


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
