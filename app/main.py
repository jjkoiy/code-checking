from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers.reviews import router as reviews_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized.")
    yield


app = FastAPI(
    title="Agent Review System",
    version="0.1.0",
    description="Multi-agent code review and test generation system (P1).",
    lifespan=lifespan,
)

app.include_router(reviews_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
