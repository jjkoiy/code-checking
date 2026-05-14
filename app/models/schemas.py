from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ── Request schemas ────────────────────────────────────────────

class ChangedFileIn(BaseModel):
    file_path: str
    language: Optional[str] = None
    content: Optional[str] = None


class CreateReviewRequest(BaseModel):
    source_type: str = "cli"
    repo_name: Optional[str] = None
    repo_path: Optional[str] = None
    base_ref: Optional[str] = None
    head_ref: Optional[str] = None
    diff_text: Optional[str] = None
    changed_files: List[ChangedFileIn] = Field(default_factory=list)


# ── Response schemas ────────────────────────────────────────────

class CreateReviewResponse(BaseModel):
    task_id: str
    status: str


class ReviewStatusResponse(BaseModel):
    task_id: str
    status: str
    source_type: Optional[str] = None
    repo_name: Optional[str] = None
    current_stage: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
