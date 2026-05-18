from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.database import Base


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewTaskEvent(Base):
    __tablename__ = "review_task_events"

    id = Column(String, primary_key=True, default=_new_id)
    task_id = Column(String, ForeignKey("review_tasks.id"), nullable=False, index=True)
    stage = Column(String, nullable=False)
    status = Column(String, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
