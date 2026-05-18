from __future__ import annotations

from types import SimpleNamespace

from app.services import review_dispatcher


def test_dispatch_review_task_enqueues_celery_job(monkeypatch) -> None:
    queued: dict[str, str] = {}

    def fake_enqueue(task_id: str):
        queued["task_id"] = task_id
        return SimpleNamespace(id="celery-job-1")

    monkeypatch.setattr(review_dispatcher, "enqueue_review_task", fake_enqueue)

    celery_task_id = review_dispatcher.dispatch_review_task("review-task-1")

    assert queued == {"task_id": "review-task-1"}
    assert celery_task_id == "celery-job-1"
