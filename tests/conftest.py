"""Shared helpers for the testsniper test suite."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# The plugin tests run pytest inside pytest. They deliberately do not pass
# "-p testsniper.plugin" to the inner run, so a broken pytest11 entry point
# fails this suite instead of hiding behind an explicit load.
pytest_plugins = ["pytester"]

GIT_ENV_ARGS = [
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
]


def write_tree(root: Path, files: dict[str, str]) -> None:
    """Write a dict of relative path -> content under root."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *GIT_ENV_ARGS, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def git_repo(root: Path) -> None:
    """Initialize root as a git repo and commit everything in it."""
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")


SAMPLE_PROJECT: dict[str, str] = {
    "pyproject.toml": (
        "[project]\n"
        'name = "sample"\n'
        'version = "0.1.0"\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        "\n"
        "[tool.testsniper]\n"
        'always_run = ["tests/smoke"]\n'
    ),
    "conftest.py": '"""Puts the project root on sys.path for pytest."""\n',
    "pkg/__init__.py": "",
    "pkg/core.py": "def core() -> int:\n    return 1\n",
    "pkg/mid.py": "from pkg.core import core\n\ndef mid() -> int:\n    return core() + 1\n",
    "pkg/top.py": "import pkg.mid\n\ndef top() -> int:\n    return pkg.mid.mid() + 1\n",
    "pkg/lonely.py": "def lonely() -> int:\n    return 99\n",
    "tests/test_core.py": (
        "from pkg.core import core\n\ndef test_core() -> None:\n    assert core() == 1\n"
    ),
    "tests/test_mid.py": (
        "import pkg.mid\n\ndef test_mid() -> None:\n    assert pkg.mid.mid() == 2\n"
    ),
    "tests/test_top.py": (
        "from pkg import top\n\ndef test_top() -> None:\n    assert top.top() == 3\n"
    ),
    "tests/smoke/test_smoke.py": "def test_smoke() -> None:\n    assert True\n",
}


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    write_tree(tmp_path, SAMPLE_PROJECT)
    return tmp_path
