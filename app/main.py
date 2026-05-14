from __future__ import annotations

import logging

from fastapi import FastAPI

from app.database import init_db
from app.routers.reviews import router as reviews_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agent Review System",
    version="0.1.0",
    description="Multi-agent code review and test generation system (P0 skeleton).",
)

app.include_router(reviews_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("Database initialized.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
