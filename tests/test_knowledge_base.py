from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import context_builder
from app.routers import knowledge
from app.services import auth, knowledge_base


def test_index_repository_collects_indexable_files_and_chunks(monkeypatch, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "app" / "demo.py").write_text("print('hello')\n" * 3, encoding="utf-8")
    (repo / "README.md").write_text("Project notes", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("secret", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "skip.py").write_text("print('skip')", encoding="utf-8")

    captured: dict[str, list[dict]] = {}

    def fake_upsert(collection: str, documents: list[dict]):
        captured["collection"] = collection
        captured["documents"] = documents
        return {"indexed_count": len(documents), "skipped": False}

    monkeypatch.setattr(knowledge_base.settings, "knowledge_max_files", 10)
    monkeypatch.setattr(knowledge_base.settings, "knowledge_max_file_chars", 1000)
    monkeypatch.setattr(knowledge_base.settings, "knowledge_chunk_chars", 20)
    monkeypatch.setattr(
        knowledge_base,
        "vector_delete_where",
        lambda collection, where: {"deleted_count": 2, "skipped": False},
    )
    monkeypatch.setattr(knowledge_base, "vector_upsert", fake_upsert)

    result = knowledge_base.index_repository("owner/repo", str(repo))

    assert result["status"] == "indexed"
    assert result["indexed_files"] == 2
    assert result["indexed_chunks"] == len(captured["documents"])
    assert result["deleted_chunks"] == 2
    assert captured["collection"] == "repository_context"
    assert {doc["metadata"]["file_path"] for doc in captured["documents"]} == {"app/demo.py", "README.md"}
    assert all(doc["metadata"]["repo_name"] == "owner/repo" for doc in captured["documents"])
    assert all(doc["metadata"]["repo_path_hash"] for doc in captured["documents"])
    assert all(doc["metadata"]["content_hash"] for doc in captured["documents"])


def test_index_repository_reports_embedding_skip(monkeypatch, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')", encoding="utf-8")
    monkeypatch.setattr(
        knowledge_base,
        "vector_delete_where",
        lambda collection, where: {"deleted_count": 0, "skipped": False},
    )
    monkeypatch.setattr(
        knowledge_base,
        "vector_upsert",
        lambda collection, documents: {
            "indexed_count": 0,
            "skipped": True,
            "skip_reason": "embedding unavailable",
        },
    )

    result = knowledge_base.index_repository(None, str(repo))

    assert result["status"] == "skipped"
    assert result["indexed_files"] == 0
    assert result["embedding_skipped"] is True
    assert result["skip_reason"] == "embedding unavailable"


def test_index_repository_clears_previous_repo_chunks(monkeypatch, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_delete(collection: str, where: dict):
        captured["delete_collection"] = collection
        captured["delete_where"] = where
        return {"deleted_count": 3, "skipped": False}

    monkeypatch.setattr(knowledge_base, "vector_delete_where", fake_delete)
    monkeypatch.setattr(
        knowledge_base,
        "vector_upsert",
        lambda collection, documents: {"indexed_count": len(documents), "skipped": False},
    )

    result = knowledge_base.index_repository("owner/repo", str(repo))

    assert captured["delete_collection"] == "repository_context"
    assert captured["delete_where"] == {"repo_name": "owner/repo"}
    assert result["deleted_chunks"] == 3


def test_index_repository_uses_python_symbol_chunks_and_redacts_secrets(monkeypatch, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text(
        "\n".join([
            "def current_user_role(request):",
            "    api_key = 'sk-testsecretvalue123456'",
            "    return request.user.role",
        ]),
        encoding="utf-8",
    )
    captured: dict[str, list[dict]] = {}

    monkeypatch.setattr(
        knowledge_base,
        "vector_delete_where",
        lambda collection, where: {"deleted_count": 0, "skipped": False},
    )

    def fake_upsert(collection: str, documents: list[dict]):
        captured["documents"] = documents
        return {"indexed_count": len(documents), "skipped": False}

    monkeypatch.setattr(knowledge_base, "vector_upsert", fake_upsert)

    result = knowledge_base.index_repository("owner/repo", str(repo))
    documents = captured["documents"]

    assert result["indexed_chunks"] == len(documents)
    assert documents[0]["metadata"]["symbol_name"] == "current_user_role"
    assert documents[0]["metadata"]["chunk_type"] == "function"
    assert documents[0]["metadata"]["start_line"] == 1
    assert "sk-testsecretvalue123456" not in documents[0]["content"]
    assert "[REDACTED_" in documents[0]["content"]


def test_knowledge_index_route_returns_index_stats(monkeypatch, tmp_path) -> None:
    app = FastAPI()
    app.include_router(knowledge.router)
    monkeypatch.setattr(auth.settings, "api_auth_enabled", False)
    monkeypatch.setattr(
        knowledge,
        "index_repository",
        lambda repo_name, repo_path: {
            "status": "indexed",
            "repo_name": repo_name or "repo",
            "repo_path": repo_path,
            "indexed_files": 1,
            "indexed_chunks": 2,
            "skipped_files": 0,
            "embedding_skipped": False,
            "skip_reason": None,
        },
    )

    response = TestClient(app).post(
        "/api/knowledge/index",
        json={"repo_name": "owner/repo", "repo_path": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json()["indexed_chunks"] == 2


def test_import_risk_rules_writes_structured_cards(monkeypatch) -> None:
    captured: dict[str, list[dict]] = {}

    def fake_upsert(collection: str, documents: list[dict]):
        captured["collection"] = collection
        captured["documents"] = documents
        return {"indexed_count": len(documents), "skipped": False}

    monkeypatch.setattr(knowledge_base, "vector_upsert", fake_upsert)

    result = knowledge_base.import_risk_rules([
        {
            "risk_id": "weak-auth-request-param",
            "title": "Admin privilege is controlled by request data",
            "severity": "high",
            "category": "security",
            "source_patterns": ["request.args"],
            "sink_patterns": ["admin"],
            "sanitizer_patterns": ["current_user"],
            "cwe": "CWE-639",
            "languages": ["python"],
            "frameworks": ["fastapi"],
            "suggestion": "Use server-side roles.",
        }
    ])

    assert result["status"] == "indexed"
    assert result["indexed_rules"] == 1
    assert captured["collection"] == "risk_rules"
    assert captured["documents"][0]["metadata"]["rule_family"] == "weak-auth-request-param"
    assert captured["documents"][0]["metadata"]["sanitizer_patterns"] == "current_user"
    assert captured["documents"][0]["metadata"]["cwe"] == "CWE-639"
    assert captured["documents"][0]["metadata"]["languages"] == "python"


def test_risk_rule_import_route_returns_index_stats(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(knowledge.router)
    monkeypatch.setattr(auth.settings, "api_auth_enabled", False)
    monkeypatch.setattr(
        knowledge,
        "import_risk_rules",
        lambda rules: {
            "status": "indexed",
            "indexed_rules": len(rules),
            "embedding_skipped": False,
            "skip_reason": None,
        },
    )

    response = TestClient(app).post(
        "/api/knowledge/risk-rules",
        json={
            "rules": [{
                "risk_id": "path-traversal",
                "title": "Request-controlled filename reaches file access",
                "severity": "high",
                "category": "security",
                "source_patterns": ["request.args"],
                "sink_patterns": ["open("],
                "suggestion": "Validate and resolve paths under an allowed base directory.",
            }]
        },
    )

    assert response.status_code == 200
    assert response.json()["indexed_rules"] == 1


def test_context_builder_queries_repository_context_when_repo_is_known(monkeypatch) -> None:
    collections: list[str] = []
    repository_filters: list[dict | None] = []

    def fake_vector_search(collection: str, query: str, top_k: int = 3, where=None):
        collections.append(collection)
        if collection == "repository_context":
            repository_filters.append(where)
        if collection == "repository_context":
            return {"documents": [{"content": "local convention", "metadata": {}}]}
        return {"documents": []}

    monkeypatch.setattr(context_builder, "vector_search", fake_vector_search)

    context = context_builder.build_context(
        diff_text=(
            "diff --git a/app/demo.py b/app/demo.py\n"
            "--- a/app/demo.py\n"
            "+++ b/app/demo.py\n"
            "@@ -1 +1 @@\n"
            "+print('hello')\n"
        ),
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        repo_name="owner/repo",
        repo_path="/repo",
    )

    assert "repository_context" in collections
    assert repository_filters == [{"repo_name": "owner/repo"}]
    assert context["relevant_project_context"][0]["content"] == "local convention"
    assert context["rag"]["document_count"] == 1
    assert context["rag"]["collections"]["repository_context"] == 1


def test_context_builder_reports_vector_fallback_degradation(monkeypatch) -> None:
    def fake_vector_search(collection: str, query: str, top_k: int = 3, where=None):
        return {
            "documents": [{"id": collection, "content": "keyword fallback doc", "metadata": {}}],
            "skipped": False,
            "skip_reason": "embedding provider unavailable",
            "retrieval": {
                "collection": collection,
                "retrieval_mode": "hybrid",
                "embedding_provider": "openai_compatible",
                "embedding_model": "text_embedding_3_small",
                "document_count": 1,
                "vector_skipped": True,
                "skip_reason": "embedding provider unavailable",
            },
        }

    monkeypatch.setattr(context_builder, "vector_search", fake_vector_search)

    context = context_builder.build_context(
        diff_text=(
            "diff --git a/app/demo.py b/app/demo.py\n"
            "--- a/app/demo.py\n"
            "+++ b/app/demo.py\n"
            "@@ -1 +1 @@\n"
            "+print('hello')\n"
        ),
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
    )

    assert context["knowledge_skipped"] is False
    assert context["rag"]["skipped"] is True
    assert context["rag"]["vector_skipped"] is True
    assert context["rag"]["degraded"] is True
    assert context["rag"]["skip_reasons"] == ["embedding provider unavailable"]
