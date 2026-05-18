from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_COLLECTIONS = {
    "review_rules",
    "security_rules",
    "test_examples",
    "project_conventions",
    "repository_context",
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


class EmbeddingProviderError(RuntimeError):
    """Raised when an external embedding provider cannot return embeddings."""


class OpenAICompatibleEmbeddingFunction:
    """OpenAI-compatible /embeddings provider for Chroma."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.model = model or settings.embedding_model
        self.api_key = api_key if api_key is not None else settings.embedding_api_key
        self.base_url = (base_url if base_url is not None else settings.embedding_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.embedding_timeout_seconds

    def name(self) -> str:
        return f"agent_review_openai_compatible_embedding_{_safe_name(self.model)}"

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def __call__(self, input: list[str]) -> list[list[float]]:
        if not input:
            return []
        if not self.api_key or not self.base_url:
            raise EmbeddingProviderError("Embedding API key and base URL are required")

        payload: dict[str, Any] = {
            "model": self.model,
            "input": input,
        }
        request = urllib.request.Request(
            url=f"{self.base_url}/embeddings",
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
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmbeddingProviderError(f"Embedding request failed: {exc}") from exc

        data = body.get("data")
        if not isinstance(data, list):
            raise EmbeddingProviderError("Embedding response did not include a data list")

        ordered = sorted(data, key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0)
        vectors: list[list[float]] = []
        for item in ordered:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list):
                raise EmbeddingProviderError("Embedding response item did not include an embedding list")
            vectors.append([float(value) for value in embedding])

        if len(vectors) != len(input):
            raise EmbeddingProviderError("Embedding response count did not match input count")
        return vectors


_client = None


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    return safe.strip("_") or "default"


def _embedding_provider_key() -> tuple[str, str]:
    provider = (settings.embedding_provider or "hash").strip().lower()
    if provider != "openai_compatible":
        return ("hash", "hash")
    if not settings.embedding_external_enabled:
        logger.info("External embedding provider configured but EMBEDDING_EXTERNAL_ENABLED is false; using hash.")
        return ("hash", "hash")
    if not settings.embedding_api_key or not settings.embedding_base_url:
        logger.info("External embedding provider configured without API key/base URL; using hash.")
        return ("hash", "hash")
    return ("openai_compatible", _safe_name(settings.embedding_model or "default"))


def get_embedding_function():
    provider, _model_key = _embedding_provider_key()
    if provider == "openai_compatible":
        return OpenAICompatibleEmbeddingFunction()
    return HashEmbeddingFunction()


def _collection_name(name: str) -> str:
    provider, model_key = _embedding_provider_key()
    if provider == "hash":
        return f"{name}__hash"
    return f"{name}__{provider}__{model_key}"


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
    collection = client.get_or_create_collection(
        name=_collection_name(name),
        embedding_function=get_embedding_function(),
    )
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


def vector_search(collection: str, query: str, top_k: int = 5) -> dict[str, Any]:
    try:
        chroma_collection = _get_collection(collection)
        result = chroma_collection.query(query_texts=[query], n_results=max(1, top_k))
    except EmbeddingProviderError as exc:
        logger.warning("Vector search skipped because embedding provider failed: %s", exc)
        return {
            "documents": [],
            "skipped": True,
            "skip_reason": str(exc),
        }

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


def vector_upsert(collection: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    if not documents:
        return {"indexed_count": 0, "skipped": False}

    try:
        chroma_collection = _get_collection(collection)
        ids = [item["id"] for item in documents]
        contents = [item["content"] for item in documents]
        metadatas = [item.get("metadata", {}) for item in documents]
        if hasattr(chroma_collection, "upsert"):
            chroma_collection.upsert(ids=ids, documents=contents, metadatas=metadatas)
        else:
            chroma_collection.add(ids=ids, documents=contents, metadatas=metadatas)
    except EmbeddingProviderError as exc:
        logger.warning("Vector upsert skipped because embedding provider failed: %s", exc)
        return {
            "indexed_count": 0,
            "skipped": True,
            "skip_reason": str(exc),
        }

    return {"indexed_count": len(documents), "skipped": False}
