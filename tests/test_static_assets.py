from __future__ import annotations

from pathlib import Path


def test_console_chinese_localization_is_utf8() -> None:
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert "中文" in html
    assert "代码审查报告" in html
    assert "暂不建议合并" in html
    assert "认证相关改动需要重点复核" in html
    assert "语言策略" in html
    for mojibake in ("涓", "鍙", "鈥", "鐢", "闃"):
        assert mojibake not in html


def test_console_chinese_view_preserves_original_finding_text() -> None:
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert "original_title" in html
    assert "original_description" in html
    assert "translation_policy" in html
    assert "technical_original_preserved" in html
    assert "API/SQL/HTTP/auth/security" in html


def test_console_supports_api_key_header() -> None:
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert 'id="apiKey"' in html
    assert '"X-API-Key"' in html
    assert "agentReviewApiKey" in html
