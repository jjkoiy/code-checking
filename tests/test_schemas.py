from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import ChangedFileIn, CreateReviewRequest


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
