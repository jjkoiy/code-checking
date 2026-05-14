from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models import CreateReviewRequest, CreateReviewResponse, ReviewStatusResponse
from app.services.review_service import create_review, get_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.post("", response_model=CreateReviewResponse, status_code=201)
def create_review_endpoint(req: CreateReviewRequest) -> CreateReviewResponse:
    task = create_review(req)
    logger.info("Created review task: %s", task.id)
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
