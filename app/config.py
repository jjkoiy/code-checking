from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs when they are not already in the environment."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_model: str = os.getenv("LLM_MODEL", "mock-reviewer")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_external_enabled: bool = _env_bool("LLM_EXTERNAL_ENABLED", False)
    llm_redaction_enabled: bool = _env_bool("LLM_REDACTION_ENABLED", True)
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    chroma_path: str = os.getenv("CHROMA_PATH", "./data/chroma")
    review_max_files: int = int(os.getenv("REVIEW_MAX_FILES", "20"))
    review_max_diff_chars: int = int(os.getenv("REVIEW_MAX_DIFF_CHARS", "60000"))
    review_max_file_content_chars: int = int(os.getenv("REVIEW_MAX_FILE_CONTENT_CHARS", "200000"))
    review_max_total_content_chars: int = int(os.getenv("REVIEW_MAX_TOTAL_CONTENT_CHARS", "500000"))
    agent_max_retry: int = int(os.getenv("AGENT_MAX_RETRY", "2"))
    validation_max_retry: int = int(os.getenv("VALIDATION_MAX_RETRY", "2"))


settings = Settings()
