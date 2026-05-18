from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

try:
    from celery import Celery
except ImportError:  # pragma: no cover - exercised through dispatcher behavior
    Celery = None  # type: ignore[assignment]


def _create_celery_app() -> Any | None:
    if Celery is None:
        return None

    app = Celery(
        "agent_review_system",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )
    return app


celery_app = _create_celery_app()


def _run_review_task(task_id: str) -> str:
    from app.services.review_service import run_review_and_save

    run_review_and_save(task_id)
    logger.info("Celery review task completed: %s", task_id)
    return task_id


if celery_app is not None:

    @celery_app.task(
        bind=True,
        name="app.worker.run_review_task",
        autoretry_for=(Exception,),
        retry_backoff=True,
        retry_kwargs={"max_retries": settings.celery_task_max_retries},
        soft_time_limit=settings.celery_task_soft_time_limit_seconds,
        time_limit=settings.celery_task_time_limit_seconds,
    )
    def run_review_task(self, task_id: str) -> str:
        return _run_review_task(task_id)

else:

    class _MissingCeleryTask:
        def delay(self, task_id: str) -> None:
            raise RuntimeError("Celery is not installed. Install requirements.txt and run a worker.")

    run_review_task = _MissingCeleryTask()


def enqueue_review_task(task_id: str):
    """Queue a review task for durable worker execution."""
    return run_review_task.delay(task_id)
