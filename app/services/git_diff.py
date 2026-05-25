from __future__ import annotations

import subprocess
import re
from pathlib import Path


class GitDiffError(ValueError):
    """Raised when local Git input cannot be converted into a reviewable diff."""


_UNSAFE_GIT_REF_RE = re.compile(r"[\s;&|`]")


def _validate_ref(name: str, value: str) -> str:
    git_ref = value.strip()
    if not git_ref:
        raise GitDiffError(f"{name} must not be empty")
    if _UNSAFE_GIT_REF_RE.search(git_ref):
        raise GitDiffError(f"{name} must not contain whitespace or shell metacharacters")
    return git_ref


def _clean_process_message(process: subprocess.CompletedProcess[str]) -> str:
    message = (process.stderr or process.stdout or "").strip()
    return message.splitlines()[0] if message else "Git command failed"


def _run_git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitDiffError("Git CLI is not installed or is not available in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitDiffError("Git command timed out after 30 seconds") from exc


def _resolve_repo_path(repo_path: str) -> Path:
    path = Path(repo_path).expanduser()
    if not path.exists():
        raise GitDiffError("repo_path does not exist")
    if not path.is_dir():
        raise GitDiffError("repo_path must be a directory")
    return path


def generate_diff_from_refs(repo_path: str, base_ref: str, head_ref: str) -> str:
    """Generate a unified Git diff for base_ref...head_ref in a local repository."""
    path = _resolve_repo_path(repo_path)
    clean_base_ref = _validate_ref("base_ref", base_ref)
    clean_head_ref = _validate_ref("head_ref", head_ref)

    repo_check = _run_git(path, ["rev-parse", "--is-inside-work-tree"])
    if repo_check.returncode != 0 or repo_check.stdout.strip() != "true":
        raise GitDiffError("repo_path must point to a Git repository")

    diff_range = f"{clean_base_ref}...{clean_head_ref}"
    diff_result = _run_git(path, ["diff", diff_range])
    if diff_result.returncode != 0:
        raise GitDiffError(f"Git diff failed: {_clean_process_message(diff_result)}")

    diff_text = diff_result.stdout
    if not diff_text.strip():
        raise GitDiffError("No reviewable diff found between base_ref and head_ref")
    return diff_text
