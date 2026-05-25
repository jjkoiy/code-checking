from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.git_diff import GitDiffError, generate_diff_from_refs


def _git(repo_path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _make_repo_with_feature_change(repo_path: Path) -> None:
    repo_path.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo_path)], check=True, capture_output=True, text=True)
    _git(repo_path, "config", "user.email", "tester@example.com")
    _git(repo_path, "config", "user.name", "Test User")
    (repo_path / "demo.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    _git(repo_path, "add", "demo.py")
    _git(repo_path, "commit", "-m", "initial")
    _git(repo_path, "checkout", "-b", "feature")
    (repo_path / "demo.py").write_text("def handler():\n    print('hello')\n    return 1\n", encoding="utf-8")
    _git(repo_path, "commit", "-am", "feature change")


def test_generate_diff_from_refs_returns_unified_git_diff(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _make_repo_with_feature_change(repo_path)

    diff_text = generate_diff_from_refs(str(repo_path), "main", "feature")

    assert "diff --git a/demo.py b/demo.py" in diff_text
    assert "+    print('hello')" in diff_text


def test_generate_diff_from_refs_rejects_non_git_directory(tmp_path: Path) -> None:
    with pytest.raises(GitDiffError, match="Git repository"):
        generate_diff_from_refs(str(tmp_path), "main", "feature")


def test_generate_diff_from_refs_rejects_empty_diff(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _make_repo_with_feature_change(repo_path)

    with pytest.raises(GitDiffError, match="No reviewable diff"):
        generate_diff_from_refs(str(repo_path), "main", "main")


def test_generate_diff_from_refs_rejects_unsafe_ref(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _make_repo_with_feature_change(repo_path)

    with pytest.raises(GitDiffError, match="shell metacharacters"):
        generate_diff_from_refs(str(repo_path), "main", "feature;rm")
