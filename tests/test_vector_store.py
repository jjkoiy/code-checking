from __future__ import annotations

import json

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

    def get(self, ids):
        return {"ids": ids}

    def add(self, ids, documents, metadatas):
        return None

    def query(self, query_texts, n_results):
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

    def get_or_create_collection(self, name, embedding_function):
        self.collection_names.append(name)
        return _FakeCollection(embedding_function)


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
