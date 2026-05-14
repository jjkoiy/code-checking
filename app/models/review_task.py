from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime

from app.database import Base


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id = Column(String, primary_key=True, default=_new_id)
    source_type = Column(String, nullable=False)
    repo_name = Column(String, nullable=True)
    repo_path = Column(String, nullable=True)
    base_ref = Column(String, nullable=True)
    head_ref = Column(String, nullable=True)
    diff_text = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")
    current_stage = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    findings_json = Column(Text, nullable=True)
    report_json = Column(Text, nullable=True)
    report_markdown = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
