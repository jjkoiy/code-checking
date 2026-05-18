from __future__ import annotations

from pydantic import ValidationError

from app.agents import report
from app.models.report import ReviewReportModel


def test_report_generate_returns_model_validated_payload() -> None:
    result = report.generate(
        aggregated_findings=[],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
        metadata={
            "agent_count": 10,
            "duration_seconds": 0.25,
            "llm_mode": "mock",
            "pipeline_status": "completed",
            "knowledge_skipped": True,
        },
    )

    validated = ReviewReportModel.model_validate(result["json_report"])

    assert validated.metadata.agent_count == 10
    assert validated.metadata.knowledge_skipped is True
    assert validated.merge_recommendation.status == "pass"


def test_report_model_rejects_invalid_merge_recommendation_status() -> None:
    result = report.generate([], [], {}, {})
    result["json_report"]["merge_recommendation"]["status"] = "maybe"

    try:
        ReviewReportModel.model_validate(result["json_report"])
    except ValidationError:
        return

    raise AssertionError("invalid merge recommendation status should fail validation")
