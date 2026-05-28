from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_COLLECTIONS = {
    "review_rules",
    "risk_rules",
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
    "risk_rules": [
        {
            "id": "risk_sql_injection_001",
            "content": json.dumps({
                "risk_id": "sql-injection",
                "title": "User input is interpolated into SQL",
                "severity": "critical",
                "category": "security",
                "bad_examples": [
                    "query = f\"SELECT * FROM users WHERE name = '{request.args.get('name')}'\"",
                    "db.execute('SELECT * FROM users WHERE id=' + user_id)",
                ],
                "safe_examples": [
                    "db.execute(text('SELECT * FROM users WHERE id=:id'), {'id': user_id})",
                ],
                "source_patterns": ["request.args", "request.form", "request.json", "input("],
                "sink_patterns": ["select ", "insert ", "update ", "delete ", "db.execute", "cursor.execute"],
                "evidence_requirements": "Show the user-controlled value and the SQL execution or SQL string construction.",
                "suggestion": "Use bound parameters or an ORM instead of string interpolation or concatenation.",
                "attack_scenario": "An attacker can alter the SQL statement with payloads such as ' OR '1'='1.",
            }),
            "metadata": {"category": "security", "severity": "critical", "rule_family": "sql-injection"},
        },
        {
            "id": "risk_weak_auth_admin_param_001",
            "content": json.dumps({
                "risk_id": "weak-auth-request-param",
                "title": "Admin privilege is controlled by request data",
                "severity": "high",
                "category": "security",
                "bad_examples": [
                    "admin = request.args.get('admin') == 'true'",
                    "if request.json.get('is_admin'): return debug_token",
                ],
                "safe_examples": [
                    "if current_user.role == 'admin': return admin_panel()",
                ],
                "source_patterns": ["request.args", "request.form", "request.json"],
                "sink_patterns": ["admin", "is_admin", "role", "permission", "debug_token"],
                "evidence_requirements": "Show that a privilege flag or role comes from client-controlled request data.",
                "suggestion": "Derive admin status from authenticated server-side identity and authorization checks.",
                "attack_scenario": "A normal user can submit admin=true or is_admin=true to access privileged behavior.",
            }),
            "metadata": {"category": "security", "severity": "high", "rule_family": "weak-auth-request-param"},
        },
        {
            "id": "risk_path_traversal_001",
            "content": json.dumps({
                "risk_id": "path-traversal",
                "title": "Request-controlled filename reaches file access",
                "severity": "high",
                "category": "security",
                "bad_examples": [
                    "filename = request.args.get('filename'); return open('/data/' + filename).read()",
                    "return send_file(request.args['path'])",
                ],
                "safe_examples": [
                    "path = safe_join(upload_root, filename)",
                    "resolved = (upload_root / filename).resolve(); assert resolved.is_relative_to(upload_root)",
                ],
                "source_patterns": ["request.args", "request.form", "request.json", "filename", "path"],
                "sink_patterns": ["open(", "send_file", "read_text(", "read_bytes(", "Path("],
                "evidence_requirements": "Show request-controlled filename/path flowing into file read or send_file without safe_join/resolve allowlist checks.",
                "suggestion": "Validate filenames against an allowlist and resolve paths under an approved base directory before reading.",
                "attack_scenario": "An attacker can request paths such as ../../etc/passwd to read files outside the intended directory.",
            }),
            "metadata": {"category": "security", "severity": "high", "rule_family": "path-traversal"},
        },
        {
            "id": "risk_client_controlled_payment_amount_001",
            "content": json.dumps({
                "risk_id": "client-controlled-payment-amount",
                "title": "Payment amount is trusted from client input",
                "severity": "critical",
                "category": "security",
                "bad_examples": [
                    "amount = request.json['amount']; return charge(amount, order_id)",
                ],
                "safe_examples": [
                    "order = load_order(order_id); return charge(order.total_amount, order.id)",
                ],
                "source_patterns": ["request.json", "request.form", "amount", "price", "total"],
                "sink_patterns": ["charge(", "pay(", "payment", "checkout"],
                "evidence_requirements": "Show the client-provided amount and the payment/charge call that uses it.",
                "suggestion": "Load the payable amount from the server-side order record and reject client-side amount overrides.",
                "attack_scenario": "An attacker can lower the amount in the request and pay less than the real order total.",
            }),
            "metadata": {"category": "security", "severity": "critical", "rule_family": "client-controlled-payment-amount"},
        },
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

    def _http_error_message(self, exc: urllib.error.HTTPError) -> str:
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except OSError:
            detail = ""
        message = f"Embedding request failed with HTTP {exc.code}"
        if detail:
            message += f": {detail[:500]}"
        return message

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
        except urllib.error.HTTPError as exc:
            raise EmbeddingProviderError(self._http_error_message(exc)) from exc
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


def _retrieval_mode() -> str:
    mode = (settings.rag_retrieval_mode or "hybrid").strip().lower()
    if mode not in {"hybrid", "vector", "keyword"}:
        return "hybrid"
    return mode


def _score_threshold() -> float:
    return max(0.0, float(settings.rag_score_threshold or 0.0))


def _matches_where(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    return all(metadata.get(key) == value for key, value in where.items())


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _keyword_index_path(collection: str) -> Path:
    return Path(settings.chroma_path) / "keyword_index" / f"{_safe_name(collection)}.json"


def _load_keyword_sidecar(collection: str) -> dict[str, dict[str, Any]]:
    path = _keyword_index_path(collection)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Keyword index could not be read for collection=%s", collection)
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(doc_id): document
        for doc_id, document in payload.items()
        if isinstance(document, dict)
    }


def _write_keyword_sidecar(collection: str, documents_by_id: dict[str, dict[str, Any]]) -> None:
    path = _keyword_index_path(collection)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(documents_by_id, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _keyword_documents(collection: str) -> list[dict[str, Any]]:
    seed_documents = [
        {
            "id": str(document["id"]),
            "content": str(document["content"]),
            "metadata": dict(document.get("metadata", {})),
        }
        for document in _SEED_DOCS.get(collection, [])
    ]
    sidecar_documents = list(_load_keyword_sidecar(collection).values())
    seed_ids = {document["id"] for document in seed_documents}
    return seed_documents + [
        document
        for document in sidecar_documents
        if document.get("id") not in seed_ids
    ]


def _keyword_upsert(collection: str, documents: list[dict[str, Any]]) -> None:
    if not documents:
        return
    documents_by_id = _load_keyword_sidecar(collection)
    for document in documents:
        doc_id = str(document["id"])
        documents_by_id[doc_id] = {
            "id": doc_id,
            "content": str(document.get("content", "")),
            "metadata": dict(document.get("metadata", {})),
        }
    _write_keyword_sidecar(collection, documents_by_id)


def _keyword_delete_where(collection: str, where: dict[str, Any]) -> int:
    if not where:
        return 0
    documents_by_id = _load_keyword_sidecar(collection)
    kept = {
        doc_id: document
        for doc_id, document in documents_by_id.items()
        if not _matches_where(document.get("metadata", {}), where)
    }
    deleted_count = len(documents_by_id) - len(kept)
    if deleted_count:
        _write_keyword_sidecar(collection, kept)
    return deleted_count


def _keyword_search(
    collection: str,
    query: str,
    top_k: int,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    scored: list[dict[str, Any]] = []
    for document in _keyword_documents(collection):
        metadata = document.get("metadata", {})
        if not isinstance(metadata, dict) or not _matches_where(metadata, where):
            continue
        content = str(document.get("content", ""))
        metadata_text = " ".join(str(value) for value in metadata.values())
        document_tokens = set(_tokenize(content + " " + metadata_text))
        overlap = query_tokens & document_tokens
        if not overlap:
            continue
        score = len(overlap) / max(len(query_tokens), 1)
        scored.append({
            "collection": collection,
            "id": document.get("id"),
            "content": content,
            "metadata": metadata,
            "score": score,
            "rank": 0,
            "retrieval_method": "keyword",
            "hit_reason": "keyword overlap: " + ", ".join(sorted(overlap)[:8]),
        })

    scored.sort(key=lambda item: item["score"], reverse=True)
    for rank, document in enumerate(scored[:max(1, top_k)], start=1):
        document["rank"] = rank
    return scored[:max(1, top_k)]


def _retrieval_stats(
    collection: str,
    mode: str,
    documents: list[dict[str, Any]],
    vector_skipped: bool = False,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    provider, model_key = _embedding_provider_key()
    return {
        "collection": collection,
        "retrieval_mode": mode,
        "embedding_provider": provider,
        "embedding_model": model_key,
        "document_count": len(documents),
        "vector_skipped": vector_skipped,
        "skip_reason": skip_reason,
    }


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


def vector_search(
    collection: str,
    query: str,
    top_k: int = 5,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if collection not in _COLLECTIONS:
        raise ValueError(f"Unsupported Chroma collection: {collection}")
    mode = _retrieval_mode()
    threshold = _score_threshold()
    vector_skipped = False
    skip_reason: str | None = None
    documents: list[dict[str, Any]] = []

    def _vector_documents() -> list[dict[str, Any]]:
        chroma_collection = _get_collection(collection)
        vector_top_k = max(1, int(settings.rag_vector_top_k or top_k))
        query_kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": vector_top_k,
        }
        if where:
            query_kwargs["where"] = where
        result = chroma_collection.query(**query_kwargs)

        vector_documents: list[dict[str, Any]] = []
        ids = result.get("ids", [[]])[0]
        contents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0] if result.get("distances") else []

        for index, doc_id in enumerate(ids):
            distance = distances[index] if index < len(distances) else None
            score = 1.0 / (1.0 + float(distance)) if distance is not None else 0.0
            vector_documents.append({
                "collection": collection,
                "id": doc_id,
                "content": contents[index] if index < len(contents) else "",
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "score": score,
                "rank": index + 1,
                "retrieval_method": "vector",
                "hit_reason": (
                    f"vector distance {float(distance):.4f}"
                    if distance is not None
                    else "vector similarity"
                ),
            })
        return vector_documents

    try:
        if mode in {"vector", "hybrid"}:
            documents.extend(_vector_documents())
    except EmbeddingProviderError as exc:
        vector_skipped = True
        skip_reason = str(exc)
        logger.warning("Vector search skipped because embedding provider failed: %s", exc)
        if mode == "vector":
            filtered = []
            return {
                "documents": filtered,
                "skipped": True,
                "skip_reason": skip_reason,
                "retrieval": _retrieval_stats(collection, mode, filtered, True, skip_reason),
            }

    if mode in {"keyword", "hybrid"}:
        keyword_top_k = max(1, int(settings.rag_keyword_top_k or top_k))
        documents.extend(_keyword_search(collection, query, keyword_top_k, where=where))

    merged: dict[str, dict[str, Any]] = {}
    for document in documents:
        doc_id = str(document.get("id") or "")
        if not doc_id:
            continue
        existing = merged.get(doc_id)
        if existing is None:
            merged[doc_id] = dict(document)
            continue
        if float(document.get("score", 0) or 0) > float(existing.get("score", 0) or 0):
            existing.update(document)
        else:
            existing["score"] = max(
                float(existing.get("score", 0) or 0),
                float(document.get("score", 0) or 0),
            )
        existing["retrieval_method"] = "hybrid"
        reasons = {
            str(existing.get("hit_reason", "")).strip(),
            str(document.get("hit_reason", "")).strip(),
        }
        existing["hit_reason"] = "; ".join(reason for reason in reasons if reason)

    filtered = [
        document
        for document in merged.values()
        if float(document.get("score", 0) or 0) >= threshold
    ]
    filtered.sort(key=lambda item: float(item.get("score", 0) or 0), reverse=True)
    filtered = filtered[:max(1, top_k)]
    for rank, document in enumerate(filtered, start=1):
        document["rank"] = rank
        document["collection"] = collection

    return {
        "documents": filtered,
        "skipped": vector_skipped and not filtered,
        "skip_reason": skip_reason,
        "retrieval": _retrieval_stats(collection, mode, filtered, vector_skipped, skip_reason),
    }


def vector_delete_where(collection: str, where: dict[str, Any]) -> dict[str, Any]:
    if not where:
        return {"deleted_count": 0, "skipped": False}

    keyword_deleted_count = _keyword_delete_where(collection, where)
    try:
        chroma_collection = _get_collection(collection)
        existing_ids: list[str] = []
        try:
            existing = chroma_collection.get(where=where)
            existing_ids = list(existing.get("ids", [])) if isinstance(existing, dict) else []
        except TypeError:
            existing_ids = []

        if not hasattr(chroma_collection, "delete"):
            return {
                "deleted_count": 0,
                "skipped": True,
                "skip_reason": "Chroma collection does not support delete",
            }

        try:
            chroma_collection.delete(where=where)
        except TypeError:
            if existing_ids:
                chroma_collection.delete(ids=existing_ids)
            else:
                raise
    except EmbeddingProviderError as exc:
        logger.warning("Vector delete skipped because embedding provider failed: %s", exc)
        return {
            "deleted_count": 0,
            "skipped": True,
            "skip_reason": str(exc),
        }

    return {"deleted_count": max(len(existing_ids), keyword_deleted_count), "skipped": False}


def vector_upsert(collection: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    if not documents:
        return {"indexed_count": 0, "skipped": False}

    _keyword_upsert(collection, documents)
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
            "indexed_count": len(documents),
            "skipped": True,
            "skip_reason": str(exc),
        }

    return {"indexed_count": len(documents), "skipped": False}
