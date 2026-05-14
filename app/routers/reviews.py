from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, BackgroundTasks

from app.models import (
    CreateReviewRequest,
    CreateReviewResponse,
    ReviewStatusResponse,
    ReviewReportResponse,
)
from app.services.review_service import create_review, get_review, run_review_and_save

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _run_pipeline_background(task_id: str) -> None:
    """Background task wrapper that catches all exceptions."""
    try:
        run_review_and_save(task_id)
    except Exception as e:
        logger.error("Background pipeline failed for task=%s: %s", task_id, e)


@router.post("", response_model=CreateReviewResponse, status_code=201)
def create_review_endpoint(
    req: CreateReviewRequest,
    background: BackgroundTasks,
) -> CreateReviewResponse:
    task = create_review(req)
    logger.info("Created review task: %s, dispatching pipeline.", task.id)

    # Run the review pipeline in the background so the API returns immediately
    background.add_task(_run_pipeline_background, task.id)

    return CreateReviewResponse(task_id=task.id, status=task.status)


@router.get("/{task_id}", response_model=ReviewStatusResponse)
def get_review_status(task_id: str) -> ReviewStatusResponse:
    task = get_review(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    return ReviewStatusResponse(
        task_id=task.id,
        status=task.status,
        source_type=task.source_type,
        repo_name=task.repo_name,
        current_stage=task.current_stage,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/{task_id}/report", response_model=ReviewReportResponse)
def get_review_report(task_id: str) -> ReviewReportResponse:
    task = get_review(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found")

    if task.status == "pending":
        raise HTTPException(status_code=202, detail="Review is still pending. Check back shortly.")

    if task.status == "running":
        return ReviewReportResponse(
            task_id=task.id,
            status=task.status,
            summary="Review is in progress. Current stage: " + (task.current_stage or "unknown"),
        )

    if task.status == "failed":
        raise HTTPException(status_code=500, detail="Review failed: " + (task.error_message or "Unknown error"))

    json_report = None
    if task.report_json:
        try:
            json_report = json.loads(task.report_json)
        except json.JSONDecodeError:
            json_report = {"raw": task.report_json}

    return ReviewReportResponse(
        task_id=task.id,
        status=task.status,
        summary=json_report.get("summary", "") if json_report else None,
        markdown_report=task.report_markdown,
        json_report=json_report,
    )
