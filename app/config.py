from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    chroma_path: str = os.getenv("CHROMA_PATH", "./data/chroma")
    review_max_files: int = int(os.getenv("REVIEW_MAX_FILES", "20"))
    review_max_diff_chars: int = int(os.getenv("REVIEW_MAX_DIFF_CHARS", "60000"))
    agent_max_retry: int = int(os.getenv("AGENT_MAX_RETRY", "2"))
    validation_max_retry: int = int(os.getenv("VALIDATION_MAX_RETRY", "2"))


settings = Settings()
