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
    monkeypatch.setattr(knowledge_base, "vector_upsert", fake_upsert)

    result = knowledge_base.index_repository("owner/repo", str(repo))

    assert result["status"] == "indexed"
    assert result["indexed_files"] == 2
    assert result["indexed_chunks"] == len(captured["documents"])
    assert captured["collection"] == "repository_context"
    assert {doc["metadata"]["file_path"] for doc in captured["documents"]} == {"app/demo.py", "README.md"}


def test_index_repository_reports_embedding_skip(monkeypatch, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')", encoding="utf-8")
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


def test_context_builder_queries_repository_context_when_repo_is_known(monkeypatch) -> None:
    collections: list[str] = []

    def fake_vector_search(collection: str, query: str, top_k: int = 3):
        collections.append(collection)
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
    assert context["relevant_project_context"][0]["content"] == "local convention"
