from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import reviews
from app.services import auth


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(reviews.router)
    return TestClient(app)


def _valid_diff() -> str:
    return (
        "diff --git a/app/demo.py b/app/demo.py\n"
        "--- a/app/demo.py\n"
        "+++ b/app/demo.py\n"
        "@@ -1 +1 @@\n"
        "+print('hello')\n"
    )


def test_api_auth_disabled_allows_review_creation(monkeypatch) -> None:
    monkeypatch.setattr(auth.settings, "api_auth_enabled", False)
    monkeypatch.setattr(reviews, "create_review", lambda req: SimpleNamespace(id="task-1", status="pending"))
    monkeypatch.setattr(reviews, "dispatch_review_task", lambda task_id: None)

    response = _client().post("/api/reviews", json={"diff_text": _valid_diff()})

    assert response.status_code == 201


def test_api_auth_enabled_rejects_missing_or_invalid_key(monkeypatch) -> None:
    monkeypatch.setattr(auth.settings, "api_auth_enabled", True)
    monkeypatch.setattr(auth.settings, "api_keys", "secret-key")
    monkeypatch.setattr(auth.settings, "rate_limit_requests_per_minute", 0)

    missing = _client().post("/api/reviews", json={"diff_text": _valid_diff()})
    invalid = _client().post(
        "/api/reviews",
        json={"diff_text": _valid_diff()},
        headers={"X-API-Key": "wrong"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_api_auth_enabled_accepts_valid_key(monkeypatch) -> None:
    monkeypatch.setattr(auth.settings, "api_auth_enabled", True)
    monkeypatch.setattr(auth.settings, "api_keys", "secret-key")
    monkeypatch.setattr(auth.settings, "rate_limit_requests_per_minute", 0)
    monkeypatch.setattr(reviews, "create_review", lambda req: SimpleNamespace(id="task-2", status="pending"))
    monkeypatch.setattr(reviews, "dispatch_review_task", lambda task_id: None)

    response = _client().post(
        "/api/reviews",
        json={"diff_text": _valid_diff()},
        headers={"X-API-Key": "secret-key"},
    )

    assert response.status_code == 201


def test_rate_limit_returns_429_after_limit(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}

        def incr(self, key: str) -> int:
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key: str, seconds: int) -> None:
            return None

    task = SimpleNamespace(
        id="task-3",
        status="completed",
        source_type="ui",
        repo_name="local-demo",
        current_stage="completed",
        error_message=None,
        created_at=None,
        updated_at=None,
    )

    fake_redis = FakeRedis()
    monkeypatch.setattr(auth.settings, "api_auth_enabled", True)
    monkeypatch.setattr(auth.settings, "api_keys", "secret-key")
    monkeypatch.setattr(auth.settings, "rate_limit_requests_per_minute", 1)
    monkeypatch.setattr(auth, "get_rate_limit_client", lambda: fake_redis)
    monkeypatch.setattr(reviews, "get_review", lambda task_id: task)

    client = _client()
    first = client.get("/api/reviews/task-3", headers={"X-API-Key": "secret-key"})
    second = client.get("/api/reviews/task-3", headers={"X-API-Key": "secret-key"})

    assert first.status_code == 200
    assert second.status_code == 429
