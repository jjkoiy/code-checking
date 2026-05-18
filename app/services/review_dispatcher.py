from __future__ import annotations

import logging

from fastapi import BackgroundTasks

from app.services.review_service import run_review_and_save

logger = logging.getLogger(__name__)


def _run_pipeline_background(task_id: str) -> None:
    """Background task wrapper that catches all exceptions."""
    try:
        run_review_and_save(task_id)
    except Exception as exc:
        logger.error("Background pipeline failed for task=%s: %s", task_id, exc)


def dispatch_review_task(background: BackgroundTasks, task_id: str) -> None:
    """Dispatch a review task for execution.

    This keeps the router independent from the current execution backend.
    """
    background.add_task(_run_pipeline_background, task_id)
