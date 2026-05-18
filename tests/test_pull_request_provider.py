from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.pull_request_provider import GhCliPullRequestProvider, PullRequestProviderError


def test_gh_cli_provider_loads_pr_metadata_and_diff(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["gh", "pr", "view"]:
            return SimpleNamespace(
                returncode=0,
                stdout='{"baseRefName":"main","headRefName":"feature","files":[{"path":"app/demo.py","additions":2,"deletions":1}]}',
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "diff --git a/app/demo.py b/app/demo.py\n"
                "--- a/app/demo.py\n"
                "+++ b/app/demo.py\n"
                "@@ -1 +1 @@\n"
                "+print('hello')\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("app.services.pull_request_provider.subprocess.run", fake_run)

    result = GhCliPullRequestProvider().fetch("owner/repo", 3)

    assert result.base_ref == "main"
    assert result.head_ref == "feature"
    assert result.changed_files == [{
        "file_path": "app/demo.py",
        "language": "python",
        "added_lines": 2,
        "deleted_lines": 1,
    }]
    assert calls[0][:5] == ["gh", "pr", "view", "3", "--repo"]
    assert calls[1][:5] == ["gh", "pr", "diff", "3", "--repo"]


def test_gh_cli_provider_reports_cli_failures(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="not authenticated")

    monkeypatch.setattr("app.services.pull_request_provider.subprocess.run", fake_run)

    with pytest.raises(PullRequestProviderError, match="not authenticated"):
        GhCliPullRequestProvider().fetch("owner/repo", 3)
