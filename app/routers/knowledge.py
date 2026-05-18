from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.models import KnowledgeIndexRequest, KnowledgeIndexResponse
from app.services.auth import require_api_access
from app.services.knowledge_base import index_repository

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"], dependencies=[Depends(require_api_access)])


@router.post("/index", response_model=KnowledgeIndexResponse)
def index_knowledge(req: KnowledgeIndexRequest) -> KnowledgeIndexResponse:
    try:
        result = index_repository(req.repo_name, req.repo_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeIndexResponse(**result)
