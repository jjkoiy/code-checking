from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


class FindingModel(BaseModel):
    id: str | None = None
    agent_name: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    category: str
    file_path: str | None = None
    line_number: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    title: str
    description: str
    evidence: str = ""
    suggestion: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    blocking: bool = False
    rule_family: str | None = None
    certainty: Literal["confirmed", "potential", "needs_context"] | None = None
    attack_scenario: str | None = None
    source_agents: list[str] = Field(default_factory=list)

    @field_validator("agent_name", "category", "title", "description")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


def normalize_findings(
    raw_findings: list[dict],
    validation_warnings: list[dict] | None = None,
) -> list[dict]:
    normalized: list[dict] = []
    for index, raw_finding in enumerate(raw_findings):
        try:
            normalized.append(FindingModel.model_validate(raw_finding).model_dump())
        except ValidationError as exc:
            warning = {
                "agent": raw_finding.get("agent_name", "unknown"),
                "index": index,
                "title": raw_finding.get("title", ""),
                "error": exc.errors()[0].get("msg", str(exc)),
            }
            if validation_warnings is not None:
                validation_warnings.append(warning)
    return normalized
