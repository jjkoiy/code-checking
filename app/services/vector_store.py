from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_COLLECTIONS = {
    "review_rules",
    "security_rules",
    "test_examples",
    "project_conventions",
}

_SEED_DOCS: dict[str, list[dict[str, Any]]] = {
    "review_rules": [
        {
            "id": "rule_python_error_handling_001",
            "content": "Python service layer should raise domain-specific exceptions instead of raw Exception.",
            "metadata": {"language": "python", "category": "maintainability"},
        }
    ],
    "security_rules": [
        {
            "id": "sec_sql_injection_001",
            "content": "Never interpolate user-controlled input directly into SQL strings. Use parameterized queries.",
            "metadata": {"category": "security", "severity": "critical"},
        }
    ],
    "test_examples": [
        {
            "id": "pytest_service_error_case_001",
            "content": "Example pytest for service layer validation errors using FastAPI TestClient or direct service calls.",
            "metadata": {"language": "python", "framework": "pytest"},
        }
    ],
    "project_conventions": [
        {
            "id": "convention_fastapi_service_layer_001",
            "content": "FastAPI route handlers should delegate business logic to service functions or classes.",
            "metadata": {"framework": "fastapi", "category": "architecture"},
        }
    ],
}


class HashEmbeddingFunction:
    """Deterministic local embeddings for Chroma without external model downloads."""

    @staticmethod
    def name() -> str:
        return "agent_review_hash_embedding"

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in input:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = [((digest[i % len(digest)] / 255.0) * 2.0) - 1.0 for i in range(64)]
            vectors.append(vector)
        return vectors


_client = None
_embedding = HashEmbeddingFunction()


def get_chroma_client():
    global _client
    if _client is not None:
        return _client
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("chromadb is not installed. Install requirements.txt to enable vector search.") from exc

    _client = chromadb.PersistentClient(path=settings.chroma_path)
    return _client


def _get_collection(name: str):
    if name not in _COLLECTIONS:
        raise ValueError(f"Unsupported Chroma collection: {name}")
    client = get_chroma_client()
    collection = client.get_or_create_collection(name=name, embedding_function=_embedding)
    _seed_collection(name, collection)
    return collection


def _seed_collection(name: str, collection) -> None:
    docs = _SEED_DOCS.get(name, [])
    if not docs:
        return
    existing = collection.get(ids=[doc["id"] for doc in docs])
    existing_ids = set(existing.get("ids", []))
    missing = [doc for doc in docs if doc["id"] not in existing_ids]
    if not missing:
        return
    collection.add(
        ids=[doc["id"] for doc in missing],
        documents=[doc["content"] for doc in missing],
        metadatas=[doc["metadata"] for doc in missing],
    )


def vector_search(collection: str, query: str, top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
    chroma_collection = _get_collection(collection)
    result = chroma_collection.query(query_texts=[query], n_results=max(1, top_k))
    documents: list[dict[str, Any]] = []
    ids = result.get("ids", [[]])[0]
    contents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0] if result.get("distances") else []

    for index, doc_id in enumerate(ids):
        distance = distances[index] if index < len(distances) else None
        score = 1.0 / (1.0 + float(distance)) if distance is not None else 0.0
        documents.append({
            "id": doc_id,
            "content": contents[index] if index < len(contents) else "",
            "metadata": metadatas[index] if index < len(metadatas) else {},
            "score": score,
        })

    return {"documents": documents}
