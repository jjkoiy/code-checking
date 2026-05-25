from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import ChangedFileIn, CreateGitReviewRequest, CreateReviewRequest


def test_create_review_request_requires_diff_or_changed_files() -> None:
    with pytest.raises(ValidationError):
        CreateReviewRequest()

    with pytest.raises(ValidationError):
        CreateReviewRequest(diff_text="   ")

    with pytest.raises(ValidationError):
        CreateReviewRequest(diff_text="11111")


def test_create_review_request_allows_diff_or_changed_files() -> None:
    assert CreateReviewRequest(
        diff_text=(
            "diff --git a/app/demo.py b/app/demo.py\n"
            "--- a/app/demo.py\n"
            "+++ b/app/demo.py\n"
            "@@ -1 +1 @@\n"
            "+print('hello')\n"
        )
    )
    assert CreateReviewRequest(
        changed_files=[ChangedFileIn(file_path="app/demo.py", content="print('hello')")]
    )
    assert CreateReviewRequest(
        source_type="github_pr",
        repo_name="owner/repo",
        pull_request_number=12,
    )


def test_github_pr_request_requires_repo_and_number() -> None:
    with pytest.raises(ValidationError, match="repo_name"):
        CreateReviewRequest(source_type="github_pr", pull_request_number=12)

    with pytest.raises(ValidationError, match="pull_request_number"):
        CreateReviewRequest(source_type="github_pr", repo_name="owner/repo")


def test_create_git_review_request_validates_local_git_input() -> None:
    request = CreateGitReviewRequest(
        repo_path="C:/repo/demo",
        base_ref="main",
        head_ref="feature/login",
    )

    assert request.repo_path == "C:/repo/demo"
    assert request.base_ref == "main"
    assert request.head_ref == "feature/login"

    with pytest.raises(ValidationError, match="repo_path"):
        CreateGitReviewRequest(repo_path=" ", base_ref="main", head_ref="feature")

    for unsafe_ref in ("feature branch", "feature;rm", "feature&run", "feature|run", "`feature`"):
        with pytest.raises(ValidationError, match="git ref"):
            CreateGitReviewRequest(repo_path="C:/repo/demo", base_ref="main", head_ref=unsafe_ref)


def test_create_review_request_rejects_changed_files_without_content_when_diff_is_absent() -> None:
    with pytest.raises(ValidationError, match="changed_files.content"):
        CreateReviewRequest(changed_files=[ChangedFileIn(file_path="app/demo.py")])


@pytest.mark.parametrize(
    "file_path",
    ["", "../secret.py", "app/../secret.py", "/tmp/secret.py", "C:/tmp/secret.py", "app/\x00secret.py"],
)
def test_changed_file_rejects_unsafe_file_paths(file_path: str) -> None:
    with pytest.raises(ValidationError):
        ChangedFileIn(file_path=file_path, content="print('hello')")


def test_create_review_request_enforces_max_files(monkeypatch) -> None:
    monkeypatch.setattr("app.models.schemas.settings.review_max_files", 1)

    with pytest.raises(ValidationError, match="REVIEW_MAX_FILES"):
        CreateReviewRequest(
            diff_text=(
                "diff --git a/app/demo.py b/app/demo.py\n"
                "--- a/app/demo.py\n"
                "+++ b/app/demo.py\n"
                "@@ -1 +1 @@\n"
                "+print('hello')\n"
            ),
            changed_files=[
                ChangedFileIn(file_path="app/a.py"),
                ChangedFileIn(file_path="app/b.py"),
            ],
        )


def test_create_review_request_enforces_diff_size_limit(monkeypatch) -> None:
    monkeypatch.setattr("app.models.schemas.settings.review_max_diff_chars", 10)

    with pytest.raises(ValidationError, match="REVIEW_MAX_DIFF_CHARS"):
        CreateReviewRequest(
            diff_text=(
                "diff --git a/app/demo.py b/app/demo.py\n"
                "--- a/app/demo.py\n"
                "+++ b/app/demo.py\n"
                "@@ -1 +1 @@\n"
                "+print('hello')\n"
            )
        )


def test_create_review_request_enforces_single_file_content_size_limit(monkeypatch) -> None:
    monkeypatch.setattr("app.models.schemas.settings.review_max_file_content_chars", 5)

    with pytest.raises(ValidationError, match="REVIEW_MAX_FILE_CONTENT_CHARS"):
        CreateReviewRequest(
            changed_files=[ChangedFileIn(file_path="app/demo.py", content="print('hello')")]
        )


def test_create_review_request_enforces_total_content_size_limit(monkeypatch) -> None:
    monkeypatch.setattr("app.models.schemas.settings.review_max_file_content_chars", 100)
    monkeypatch.setattr("app.models.schemas.settings.review_max_total_content_chars", 10)

    with pytest.raises(ValidationError, match="REVIEW_MAX_TOTAL_CONTENT_CHARS"):
        CreateReviewRequest(
            changed_files=[
                ChangedFileIn(file_path="app/a.py", content="12345"),
                ChangedFileIn(file_path="app/b.py", content="678901"),
            ]
        )
