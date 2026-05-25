from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.models import (
    CreateGitReviewRequest,
    CreateReviewRequest,
    CreateReviewResponse,
    ReviewTaskEventResponse,
    ReviewStatusResponse,
    ReviewReportResponse,
)
from app.services.review_dispatcher import dispatch_review_task
from app.services.review_service import create_review, get_review, list_review_events
from app.services.auth import require_api_access
from app.services.git_diff import GitDiffError, generate_diff_from_refs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"], dependencies=[Depends(require_api_access)])


def _load_report_json(raw_report: str | None) -> dict | None:
    if not raw_report:
        return None
    try:
        loaded = json.loads(raw_report)
    except json.JSONDecodeError:
        return {"raw": raw_report}
    return loaded if isinstance(loaded, dict) else {"raw": loaded}


def _failed_report_json(error_message: str | None, json_report: dict | None) -> dict:
    if json_report is not None:
        return json_report
    message = error_message or "Unknown error"
    return {
        "summary": "Review failed before a complete report could be generated.",
        "pipeline_errors": [message],
    }


def _dispatch_created_task(task) -> None:
    if task.status == "pending":
        logger.info("Created review task: %s, dispatching pipeline.", task.id)
        dispatch_review_task(task.id)
    else:
        logger.info("Created review task: %s with status=%s.", task.id, task.status)


@router.post("", response_model=CreateReviewResponse, status_code=201)
def create_review_endpoint(
    req: CreateReviewRequest,
) -> CreateReviewResponse:
    task = create_review(req)
    _dispatch_created_task(task)

    return CreateReviewResponse(task_id=task.id, status=task.status)


@router.post("/from-git", response_model=CreateReviewResponse, status_code=201)
def create_review_from_git_endpoint(
    req: CreateGitReviewRequest,
) -> CreateReviewResponse:
    try:
        diff_text = generate_diff_from_refs(req.repo_path, req.base_ref, req.head_ref)
        review_req = CreateReviewRequest(
            source_type="local_git",
            repo_name=req.repo_name or Path(req.repo_path).expanduser().name or "local-repo",
            repo_path=req.repo_path,
            base_ref=req.base_ref,
            head_ref=req.head_ref,
            diff_text=diff_text,
            changed_files=[],
        )
    except (GitDiffError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task = create_review(review_req)
    _dispatch_created_task(task)

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


@router.get("/{task_id}/events", response_model=list[ReviewTaskEventResponse])
def get_review_events(task_id: str) -> list[ReviewTaskEventResponse]:
    task = get_review(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    return [
        ReviewTaskEventResponse(
            id=event.id,
            task_id=event.task_id,
            stage=event.stage,
            status=event.status,
            error_message=event.error_message,
            created_at=event.created_at,
        )
        for event in list_review_events(task_id)
    ]


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
        json_report = _failed_report_json(task.error_message, _load_report_json(task.report_json))
        return ReviewReportResponse(
            task_id=task.id,
            status=task.status,
            summary=json_report.get("summary", task.error_message),
            markdown_report=task.report_markdown,
            json_report=json_report,
            generated_tests=json_report.get("generated_tests", []),
        )

    json_report = _load_report_json(task.report_json)

    return ReviewReportResponse(
        task_id=task.id,
        status=task.status,
        summary=json_report.get("summary", "") if json_report else None,
        markdown_report=task.report_markdown,
        json_report=json_report,
        generated_tests=json_report.get("generated_tests", []) if json_report else [],
    )
