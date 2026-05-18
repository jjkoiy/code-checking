from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

OPENAI_COMPATIBLE_PROVIDERS = {"openai", "deepseek"}


@dataclass
class LLMResponse:
    content: str
    parsed_json: Any | None = None
    usage: dict[str, Any] | None = None


class LLMClient:
    """Small OpenAI-compatible chat client used by P2 agents."""

    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        self.provider = provider or settings.llm_provider
        self.model = model or settings.llm_model
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        self.timeout = settings.llm_timeout_seconds

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: str = "json",
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        if self.provider == "mock" or not self.api_key or not settings.llm_external_enabled:
            logger.info("LLM client running in mock mode; provider=%s model=%s", self.provider, self.model)
            return LLMResponse(content="[]", parsed_json=[])

        if self.provider not in OPENAI_COMPATIBLE_PROVIDERS:
            raise ValueError(f"Unsupported LLM_PROVIDER: {self.provider}")

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed_json = None
        if response_format == "json" and content:
            try:
                parsed_json = json.loads(content)
            except json.JSONDecodeError:
                logger.warning("LLM returned non-JSON content despite JSON response format.")

        return LLMResponse(
            content=content,
            parsed_json=parsed_json,
            usage=body.get("usage", {}),
        )


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def call_llm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    response_format: str = "json",
) -> dict[str, Any]:
    response = get_llm_client().call(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        response_format=response_format,
    )
    return {
        "content": response.content,
        "parsed_json": response.parsed_json,
        "usage": response.usage or {},
    }
