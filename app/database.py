from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db() -> None:
    import app.models.review_task  # noqa: F401 — ensure ORM model is registered
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    """Apply tiny SQLite schema additions until a real migration tool exists."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if not inspector.has_table("review_tasks"):
        return

    existing = {column["name"] for column in inspector.get_columns("review_tasks")}
    if "changed_files_json" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE review_tasks ADD COLUMN changed_files_json TEXT"))
