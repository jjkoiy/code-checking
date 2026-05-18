from __future__ import annotations

import json

from app.services import llm_client


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps({
            "choices": [
                {"message": {"content": json.dumps({"findings": []})}},
            ],
            "usage": {"total_tokens": 12},
        }).encode("utf-8")


def test_deepseek_provider_uses_openai_compatible_chat_completions(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm_client.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(llm_client.settings, "llm_external_enabled", True)
    monkeypatch.setattr(llm_client.settings, "llm_timeout_seconds", 30)

    client = llm_client.LLMClient(provider="deepseek", model="deepseek-chat")
    response = client.call(
        system_prompt="Return JSON.",
        user_prompt="Review this diff.",
        response_format="json",
    )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 30
    assert response.parsed_json == {"findings": []}


def test_client_returns_mock_when_external_llm_is_disabled(monkeypatch) -> None:
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not be called when external LLM is disabled")

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fail_urlopen)
    monkeypatch.setattr(llm_client.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_client.settings, "llm_external_enabled", False)

    client = llm_client.LLMClient(provider="deepseek", model="deepseek-chat")
    response = client.call(
        system_prompt="Return JSON.",
        user_prompt="Review this diff.",
        response_format="json",
    )

    assert response.parsed_json == []
