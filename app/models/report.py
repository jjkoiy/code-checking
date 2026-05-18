from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportMetadataModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_count: int = Field(default=0, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    llm_mode: str = "mock"
    pipeline_status: Literal["completed", "failed"] = "completed"
    knowledge_skipped: bool = False


class ReviewScopeModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    file_count: int = Field(default=0, ge=0)
    languages: list[str] = Field(default_factory=list)
    mode: str = "added_lines_only"
    added_lines: int | str | None = None
    has_reviewable_content: bool = True


class MergeRecommendationModel(BaseModel):
    status: Literal["pass", "caution", "needs_review", "block"]
    label: str
    reason: str


class ReviewReportModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str
    metadata: ReportMetadataModel
    review_scope: ReviewScopeModel
    llm_mode: str
    total_findings: int = Field(ge=0)
    blocking_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    high_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    low_count: int = Field(ge=0)
    merge_recommendation: MergeRecommendationModel
    high_risk_findings: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    test_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    generated_tests: list[dict[str, Any]] = Field(default_factory=list)
    validation_result: dict[str, Any] = Field(default_factory=dict)
    validation_warnings: list[dict[str, Any]] = Field(default_factory=list)


class ReportGenerationResultModel(BaseModel):
    summary: str
    markdown_report: str
    json_report: ReviewReportModel
