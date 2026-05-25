from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import settings


# ── Request schemas ────────────────────────────────────────────

class ChangedFileIn(BaseModel):
    file_path: str
    language: Optional[str] = None
    content: Optional[str] = None

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        file_path = value.strip()
        normalized = file_path.replace("\\", "/")
        if not file_path:
            raise ValueError("file_path must not be empty")
        if re.search(r"[\x00-\x1f\x7f]", file_path):
            raise ValueError("file_path must not contain control characters")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
            raise ValueError("file_path must be a relative repository path")
        if ".." in normalized:
            raise ValueError("file_path must not contain '..'")
        return file_path


_GIT_DIFF_HEADER_RE = re.compile(r"^diff --git a/.+ b/.+$", re.MULTILINE)
_GIT_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)


def _looks_like_git_diff(diff_text: str) -> bool:
    """Return whether text has enough unified Git diff structure to review."""
    return bool(
        _GIT_DIFF_HEADER_RE.search(diff_text)
        and _GIT_DIFF_HUNK_RE.search(diff_text)
    )


class CreateReviewRequest(BaseModel):
    source_type: str = "cli"
    repo_name: Optional[str] = None
    pull_request_number: Optional[int] = Field(default=None, ge=1)
    repo_path: Optional[str] = None
    base_ref: Optional[str] = None
    head_ref: Optional[str] = None
    diff_text: Optional[str] = None
    changed_files: List[ChangedFileIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_review_input(self) -> "CreateReviewRequest":
        is_github_pr = self.source_type == "github_pr"
        if is_github_pr:
            if not self.repo_name:
                raise ValueError("repo_name is required when source_type is github_pr")
            if self.pull_request_number is None:
                raise ValueError("pull_request_number is required when source_type is github_pr")
            return self

        has_diff = bool(self.diff_text and self.diff_text.strip())
        has_changed_files = bool(self.changed_files)
        content_lengths = [
            len(changed.content)
            for changed in self.changed_files
            if changed.content is not None
        ]
        has_content = any(changed.content and changed.content.strip() for changed in self.changed_files)
        if not has_diff and not has_changed_files:
            raise ValueError("diff_text or changed_files must be provided")
        if not has_diff and not has_content:
            raise ValueError("diff_text or non-empty changed_files.content must be provided")
        if not has_diff:
            missing_content = [
                changed.file_path
                for changed in self.changed_files
                if not (changed.content and changed.content.strip())
            ]
            if missing_content:
                raise ValueError(
                    "changed_files.content must be provided for every changed file when diff_text is absent: "
                    + ", ".join(missing_content)
                )
        if has_diff and not _looks_like_git_diff(self.diff_text or ""):
            raise ValueError(
                "diff_text must be a unified Git diff containing a 'diff --git' header "
                "and at least one hunk header like '@@ -1 +1 @@'. "
                "Use changed_files when submitting raw file content."
            )
        if len(self.changed_files) > settings.review_max_files:
            raise ValueError(
                f"changed_files exceeds REVIEW_MAX_FILES limit of {settings.review_max_files}"
            )
        if self.diff_text and len(self.diff_text) > settings.review_max_diff_chars:
            raise ValueError(
                f"diff_text exceeds REVIEW_MAX_DIFF_CHARS limit of {settings.review_max_diff_chars}"
            )
        oversized_files = [
            changed.file_path
            for changed in self.changed_files
            if changed.content is not None
            and len(changed.content) > settings.review_max_file_content_chars
        ]
        if oversized_files:
            raise ValueError(
                "changed_files.content exceeds REVIEW_MAX_FILE_CONTENT_CHARS limit of "
                f"{settings.review_max_file_content_chars}: "
                + ", ".join(oversized_files)
            )
        total_content_chars = sum(content_lengths)
        if total_content_chars > settings.review_max_total_content_chars:
            raise ValueError(
                "changed_files content exceeds REVIEW_MAX_TOTAL_CONTENT_CHARS limit of "
                f"{settings.review_max_total_content_chars}"
            )
        return self


_UNSAFE_GIT_REF_RE = re.compile(r"[\s;&|`]")


class CreateGitReviewRequest(BaseModel):
    repo_path: str
    base_ref: str = "main"
    head_ref: str
    repo_name: Optional[str] = None

    @field_validator("repo_path")
    @classmethod
    def validate_repo_path(cls, value: str) -> str:
        repo_path = value.strip()
        if not repo_path:
            raise ValueError("repo_path must not be empty")
        if re.search(r"[\x00-\x1f\x7f]", repo_path):
            raise ValueError("repo_path must not contain control characters")
        return repo_path

    @field_validator("base_ref", "head_ref")
    @classmethod
    def validate_git_ref(cls, value: str) -> str:
        git_ref = value.strip()
        if not git_ref:
            raise ValueError("git ref must not be empty")
        if _UNSAFE_GIT_REF_RE.search(git_ref):
            raise ValueError("git ref must not contain whitespace or shell metacharacters")
        return git_ref


# ── Response schemas ────────────────────────────────────────────

class CreateReviewResponse(BaseModel):
    task_id: str
    status: str


class ReviewTaskEventResponse(BaseModel):
    id: str
    task_id: str
    stage: str
    status: str
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


class ReviewStatusResponse(BaseModel):
    task_id: str
    status: str
    source_type: Optional[str] = None
    repo_name: Optional[str] = None
    current_stage: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReviewReportResponse(BaseModel):
    task_id: str
    status: str
    summary: Optional[str] = None
    markdown_report: Optional[str] = None
    json_report: Optional[dict] = None
    generated_tests: List[Any] = Field(default_factory=list)


class KnowledgeIndexRequest(BaseModel):
    repo_name: Optional[str] = None
    repo_path: str


class KnowledgeIndexResponse(BaseModel):
    status: str
    repo_name: str
    repo_path: str
    indexed_files: int
    indexed_chunks: int
    skipped_files: int
    embedding_skipped: bool = False
    skip_reason: Optional[str] = None
