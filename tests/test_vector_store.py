from __future__ import annotations

from io import BytesIO
import json
import urllib.error

from app.services import vector_store


class _FakeEmbeddingResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps({
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        }).encode("utf-8")


class _FakeCollection:
    def __init__(self, embedding_function):
        self.embedding_function = embedding_function
        self.last_query_kwargs = None
        self.deleted_where = None

    def get(self, ids=None, where=None):
        if where:
            return {"ids": ["doc-1", "doc-2"]}
        return {"ids": ids}

    def add(self, ids, documents, metadatas):
        return None

    def delete(self, where=None, ids=None):
        self.deleted_where = where
        self.deleted_ids = ids
        return None

    def query(self, query_texts, n_results, where=None):
        self.last_query_kwargs = {
            "query_texts": query_texts,
            "n_results": n_results,
            "where": where,
        }
        self.embedding_function(query_texts)
        return {
            "ids": [["doc-1"]],
            "documents": [["content"]],
            "metadatas": [[{"kind": "test"}]],
            "distances": [[0.5]],
        }


class _FakeClient:
    def __init__(self):
        self.collection_names: list[str] = []
        self.collections: list[_FakeCollection] = []

    def get_or_create_collection(self, name, embedding_function):
        self.collection_names.append(name)
        collection = _FakeCollection(embedding_function)
        self.collections.append(collection)
        return collection


def test_hash_embedding_keeps_local_64_dimension_vectors() -> None:
    embedding = vector_store.HashEmbeddingFunction()

    vectors = embedding(["same text", "same text"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 64
    assert vectors[0] == vectors[1]


def test_openai_compatible_embedding_uses_embeddings_endpoint(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeEmbeddingResponse()

    monkeypatch.setattr(vector_store.urllib.request, "urlopen", fake_urlopen)

    embedding = vector_store.OpenAICompatibleEmbeddingFunction(
        model="text-embedding-3-small",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        timeout=12,
    )

    vectors = embedding(["alpha", "beta"])

    assert captured["url"] == "https://api.example.com/v1/embeddings"
    assert captured["payload"] == {
        "model": "text-embedding-3-small",
        "input": ["alpha", "beta"],
    }
    assert captured["timeout"] == 12
    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_openai_compatible_embedding_includes_http_error_body(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"message":"invalid model"}'),
        )

    monkeypatch.setattr(vector_store.urllib.request, "urlopen", fake_urlopen)

    embedding = vector_store.OpenAICompatibleEmbeddingFunction(
        model="missing-model",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        timeout=12,
    )

    try:
        embedding(["alpha"])
    except vector_store.EmbeddingProviderError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected embedding provider failure")

    assert "HTTP 400" in message
    assert "invalid model" in message


def test_external_embedding_disabled_uses_hash_collection(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(vector_store, "get_chroma_client", lambda: client)
    monkeypatch.setattr(vector_store.settings, "embedding_provider", "openai_compatible")
    monkeypatch.setattr(vector_store.settings, "embedding_external_enabled", False)
    monkeypatch.setattr(vector_store.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(vector_store.settings, "embedding_base_url", "https://api.example.com/v1")

    result = vector_store.vector_search("review_rules", "query")

    assert result["documents"]
    assert client.collection_names == ["review_rules__hash"]


def test_external_embedding_uses_provider_and_model_collection(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(vector_store, "get_chroma_client", lambda: client)
    monkeypatch.setattr(vector_store.settings, "embedding_provider", "openai_compatible")
    monkeypatch.setattr(vector_store.settings, "embedding_external_enabled", True)
    monkeypatch.setattr(vector_store.settings, "embedding_model", "text-embedding-3-small")
    monkeypatch.setattr(vector_store.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(vector_store.settings, "embedding_base_url", "https://api.example.com/v1")

    def fake_call(self, input):
        return [[0.1, 0.2, 0.3] for _ in input]

    monkeypatch.setattr(vector_store.OpenAICompatibleEmbeddingFunction, "__call__", fake_call)

    result = vector_store.vector_search("review_rules", "query")

    assert result["documents"]
    assert client.collection_names == ["review_rules__openai_compatible__text_embedding_3_small"]


def test_embedding_provider_failure_skips_vector_search(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(vector_store, "get_chroma_client", lambda: client)
    monkeypatch.setattr(vector_store.settings, "embedding_provider", "openai_compatible")
    monkeypatch.setattr(vector_store.settings, "embedding_external_enabled", True)
    monkeypatch.setattr(vector_store.settings, "embedding_model", "text-embedding-3-small")
    monkeypatch.setattr(vector_store.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(vector_store.settings, "embedding_base_url", "https://api.example.com/v1")

    def fail_call(self, input):
        raise vector_store.EmbeddingProviderError("provider unavailable")

    monkeypatch.setattr(vector_store.OpenAICompatibleEmbeddingFunction, "__call__", fail_call)

    result = vector_store.vector_search("review_rules", "query")

    assert result["documents"] == []
    assert result["skipped"] is True
    assert "provider unavailable" in result["skip_reason"]


def test_vector_search_passes_metadata_filter(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(vector_store, "get_chroma_client", lambda: client)
    monkeypatch.setattr(vector_store.settings, "embedding_provider", "hash")
    monkeypatch.setattr(vector_store.settings, "embedding_external_enabled", False)
    monkeypatch.setattr(vector_store.settings, "rag_vector_top_k", 7)

    result = vector_store.vector_search(
        "repository_context",
        "query",
        top_k=7,
        where={"repo_name": "owner/repo"},
    )

    assert result["documents"]
    assert client.collections[0].last_query_kwargs == {
        "query_texts": ["query"],
        "n_results": 7,
        "where": {"repo_name": "owner/repo"},
    }


def test_vector_search_uses_configured_vector_top_k(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(vector_store, "get_chroma_client", lambda: client)
    monkeypatch.setattr(vector_store.settings, "embedding_provider", "hash")
    monkeypatch.setattr(vector_store.settings, "embedding_external_enabled", False)
    monkeypatch.setattr(vector_store.settings, "rag_vector_top_k", 11)

    result = vector_store.vector_search("review_rules", "query", top_k=3)

    assert result["documents"]
    assert client.collections[0].last_query_kwargs["n_results"] == 11


def test_vector_delete_where_deletes_by_metadata_filter(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(vector_store, "get_chroma_client", lambda: client)

    result = vector_store.vector_delete_where(
        "repository_context",
        {"repo_name": "owner/repo"},
    )

    assert result == {"deleted_count": 2, "skipped": False}
    assert client.collections[0].deleted_where == {"repo_name": "owner/repo"}


def test_hybrid_retrieval_falls_back_to_keyword_when_embedding_fails(monkeypatch, tmp_path) -> None:
    client = _FakeClient()
    monkeypatch.setattr(vector_store.settings, "chroma_path", str(tmp_path / "chroma"))
    monkeypatch.setattr(vector_store, "get_chroma_client", lambda: client)
    monkeypatch.setattr(vector_store.settings, "rag_retrieval_mode", "hybrid")
    monkeypatch.setattr(vector_store.settings, "embedding_provider", "openai_compatible")
    monkeypatch.setattr(vector_store.settings, "embedding_external_enabled", True)
    monkeypatch.setattr(vector_store.settings, "embedding_model", "text-embedding-3-small")
    monkeypatch.setattr(vector_store.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(vector_store.settings, "embedding_base_url", "https://api.example.com/v1")

    def fail_call(self, input):
        raise vector_store.EmbeddingProviderError("provider unavailable")

    monkeypatch.setattr(vector_store.OpenAICompatibleEmbeddingFunction, "__call__", fail_call)

    upsert_result = vector_store.vector_upsert(
        "review_rules",
        [{
            "id": "keyword-rule",
            "content": "FastAPI auth service rules should use server-side roles.",
            "metadata": {"category": "security"},
        }],
    )
    result = vector_store.vector_search("review_rules", "auth service roles", top_k=3)

    assert upsert_result["skipped"] is False
    assert upsert_result["indexed_count"] == 1
    assert result["documents"][0]["id"] == "keyword-rule"
    assert result["documents"][0]["collection"] == "review_rules"
    assert result["documents"][0]["retrieval_method"] == "keyword"
    assert result["retrieval"]["vector_skipped"] is True
