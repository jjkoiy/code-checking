from __future__ import annotations

import logging

from app.worker import enqueue_review_task

logger = logging.getLogger(__name__)


def dispatch_review_task(task_id: str) -> str | None:
    """Dispatch a review task for execution.

    This keeps the router independent from the current execution backend.
    """
    async_result = enqueue_review_task(task_id)
    celery_task_id = getattr(async_result, "id", None)
    logger.info("Dispatched review task=%s to Celery job=%s.", task_id, celery_task_id)
    return celery_task_id
