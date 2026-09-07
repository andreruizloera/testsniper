"""Thin wrapper around the git CLI for change detection."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from testsniper.scanner import SKIP_DIRS


class GitError(Exception):
    """A git operation failed in an expected, user-explainable way."""


def _git(cwd: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()
        raise GitError(detail[0] if detail else f"git {args[0]} failed")
    return proc.stdout


def repo_root(cwd: Path) -> Path:
    """The repository root containing cwd."""
    try:
        out = _git(cwd, "rev-parse", "--show-toplevel")
    except GitError as exc:
        raise GitError(f"not inside a git repository: {cwd}") from exc
    return Path(out.strip())


def changed_files(root: Path, ref: str | None = None, staged: bool = False) -> list[str]:
    """Changed file paths relative to the repo root.

    Default compares the working tree (including untracked files) against
    HEAD. ``staged`` compares the index against HEAD. ``ref`` compares the
    working tree against that revision.
    """
    if staged:
        out = _git(root, "diff", "--name-only", "--cached")
        files = out.splitlines()
    else:
        target = ref or "HEAD"
        try:
            out = _git(root, "diff", "--name-only", target, "--")
        except GitError as exc:
            if ref is None:
                raise GitError("repository has no commits yet; commit once first") from exc
            raise GitError(f"unknown revision: {ref}") from exc
        files = out.splitlines()
        if ref is None:
            untracked = _git(root, "ls-files", "--others", "--exclude-standard")
            files.extend(untracked.splitlines())
    cleaned = {f.strip() for f in files if f.strip()}
    return sorted(f for f in cleaned if not _is_generated(f))


def file_at_ref(root: Path, relpath: str, ref: str = "HEAD") -> str | None:
    """The contents of a file at a revision, or None when it is not there.

    A file that the revision does not have (a new file, or one git cannot
    show for any other reason) is not an error here: the caller uses the
    absence as the answer.
    """
    try:
        return _git(root, "show", f"{ref}:{relpath}")
    except GitError:
        return None


def _is_generated(relpath: str) -> bool:
    """Skip build artifacts (pyc files, virtualenvs) even when untracked."""
    parts = PurePosixPath(relpath).parts
    return any(part in SKIP_DIRS for part in parts) or relpath.endswith((".pyc", ".pyo"))
