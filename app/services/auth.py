from __future__ import annotations

import time
from functools import lru_cache

from fastapi import Header, HTTPException, Request, status

from app.config import settings

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - depends on optional runtime install
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        pass


def _configured_api_keys() -> set[str]:
    return {
        item.strip()
        for item in settings.api_keys.split(",")
        if item.strip()
    }


@lru_cache(maxsize=1)
def get_rate_limit_client():
    if Redis is None:
        raise RuntimeError("redis is not installed. Install requirements.txt to enable rate limiting.")
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _rate_limit_identity(request: Request, api_key: str | None) -> str:
    if api_key:
        return f"key:{api_key}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def _check_rate_limit(request: Request, api_key: str | None) -> None:
    limit = settings.rate_limit_requests_per_minute
    if limit <= 0:
        return

    identity = _rate_limit_identity(request, api_key)
    window = int(time.time() // 60)
    redis_key = f"rate_limit:review_api:{identity}:{window}"
    try:
        client = get_rate_limit_client()
        count = int(client.incr(redis_key))
        if count == 1:
            client.expire(redis_key, 65)
    except (RedisError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Rate limiter unavailable: {exc}",
        ) from exc

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )


def require_api_access(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    if not settings.api_auth_enabled:
        return

    valid_keys = _configured_api_keys()
    if not valid_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is enabled but no API keys are configured",
        )

    if not x_api_key or x_api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

    _check_rate_limit(request, x_api_key)
