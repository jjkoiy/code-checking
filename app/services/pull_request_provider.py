from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from app.agents.diff_utils import detect_language


class PullRequestProviderError(RuntimeError):
    """Raised when pull request input cannot be loaded."""


@dataclass
class PullRequestReviewInput:
    diff_text: str
    changed_files: list[dict] = field(default_factory=list)
    base_ref: str | None = None
    head_ref: str | None = None


class PullRequestProvider(Protocol):
    def fetch(self, repo_name: str, pull_request_number: int) -> PullRequestReviewInput:
        ...


class GhCliPullRequestProvider:
    """Load pull request review input through GitHub CLI."""

    def fetch(self, repo_name: str, pull_request_number: int) -> PullRequestReviewInput:
        pr = str(pull_request_number)
        metadata = self._run_json([
            "gh",
            "pr",
            "view",
            pr,
            "--repo",
            repo_name,
            "--json",
            "baseRefName,headRefName,files",
        ])
        diff_text = self._run_text([
            "gh",
            "pr",
            "diff",
            pr,
            "--repo",
            repo_name,
        ])
        if not diff_text.strip():
            raise PullRequestProviderError("GitHub PR diff is empty")

        changed_files = []
        for item in metadata.get("files") or []:
            path = item.get("path")
            if not path:
                continue
            changed_files.append({
                "file_path": path,
                "language": detect_language(path),
                "added_lines": item.get("additions", 0),
                "deleted_lines": item.get("deletions", 0),
            })

        return PullRequestReviewInput(
            diff_text=diff_text,
            changed_files=changed_files,
            base_ref=metadata.get("baseRefName"),
            head_ref=metadata.get("headRefName"),
        )

    def _run_json(self, command: list[str]) -> dict:
        output = self._run_text(command)
        try:
            loaded = json.loads(output)
        except json.JSONDecodeError as exc:
            raise PullRequestProviderError("GitHub CLI returned invalid JSON") from exc
        if not isinstance(loaded, dict):
            raise PullRequestProviderError("GitHub CLI returned an unexpected JSON payload")
        return loaded

    def _run_text(self, command: list[str]) -> str:
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError as exc:
            raise PullRequestProviderError("GitHub CLI is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise PullRequestProviderError("GitHub CLI command timed out") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "GitHub CLI command failed").strip()
            raise PullRequestProviderError(message)
        return result.stdout


def fetch_pull_request_review_input(
    repo_name: str,
    pull_request_number: int,
    provider: PullRequestProvider | None = None,
) -> PullRequestReviewInput:
    return (provider or GhCliPullRequestProvider()).fetch(repo_name, pull_request_number)
