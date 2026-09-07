"""Tests for the CLI and git change detection."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import SAMPLE_PROJECT, git, git_repo, write_tree

from testsniper.cli import main
from testsniper.gitio import GitError, changed_files, file_at_ref, repo_root


@pytest.fixture
def sample_repo(sample_project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    git_repo(sample_project)
    monkeypatch.chdir(sample_project)
    return sample_project


def test_repo_root_outside_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        repo_root(tmp_path)


def test_changed_files_working_tree_and_untracked(sample_repo: Path) -> None:
    (sample_repo / "pkg/core.py").write_text("def core() -> int:\n    return 2\n")
    write_tree(sample_repo, {"pkg/new.py": "x = 1\n"})
    assert changed_files(sample_repo) == ["pkg/core.py", "pkg/new.py"]


def test_changed_files_skips_build_artifacts(sample_repo: Path) -> None:
    write_tree(
        sample_repo,
        {
            "pkg/__pycache__/core.cpython-313.pyc": "",
            "stray.pyc": "",
            "pkg/new.py": "x = 1\n",
        },
    )
    assert changed_files(sample_repo) == ["pkg/new.py"]


def test_changed_files_staged_only(sample_repo: Path) -> None:
    (sample_repo / "pkg/core.py").write_text("def core() -> int:\n    return 2\n")
    (sample_repo / "pkg/top.py").write_text("import pkg.mid\n")
    git(sample_repo, "add", "pkg/core.py")
    assert changed_files(sample_repo, staged=True) == ["pkg/core.py"]


def test_changed_files_against_ref(sample_repo: Path) -> None:
    (sample_repo / "pkg/core.py").write_text("def core() -> int:\n    return 2\n")
    git(sample_repo, "add", "-A")
    git(sample_repo, "commit", "-q", "-m", "change core")
    assert changed_files(sample_repo, ref="HEAD~1") == ["pkg/core.py"]
    assert changed_files(sample_repo) == []


def test_changed_files_unknown_ref(sample_repo: Path) -> None:
    with pytest.raises(GitError, match="unknown revision"):
        changed_files(sample_repo, ref="no-such-ref")


def test_cli_no_changes(sample_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "No changes detected" in capsys.readouterr().out


def test_cli_list_output(sample_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (sample_repo / "pkg/core.py").write_text("def core() -> int:\n    return 1\n\nX = 1\n")
    assert main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "Changed: pkg/core.py" in out
    assert "Selected (would run 4 of 4 tests):" in out
    assert "tests/test_core.py  [distance 1]" in out
    assert "tests/smoke/test_smoke.py  [always]" in out
    assert "Selection confidence: High" in out


def test_cli_list_staged(sample_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (sample_repo / "pkg/top.py").write_text("import pkg.mid\n\nX = 1\n")
    git(sample_repo, "add", "pkg/top.py")
    assert main(["--staged", "--list"]) == 0
    out = capsys.readouterr().out
    assert "Changed: pkg/top.py" in out
    assert "tests/test_top.py" in out
    assert "tests/test_core.py" not in out


def test_cli_list_against_ref(sample_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (sample_repo / "pkg/mid.py").write_text(
        "from pkg.core import core\n\ndef mid() -> int:\n    return core() + 1\n\nX = 1\n"
    )
    git(sample_repo, "add", "-A")
    git(sample_repo, "commit", "-q", "-m", "change mid")
    assert main(["HEAD~1", "--list"]) == 0
    out = capsys.readouterr().out
    assert "Changed: pkg/mid.py" in out
    assert "tests/test_mid.py" in out


def test_cli_staged_plus_ref_is_an_error(
    sample_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["HEAD~1", "--staged"]) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_cli_outside_repo_is_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_unreached_module_message(
    sample_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (sample_repo / "pkg/lonely.py").write_text("def lonely() -> int:\n    return 100\n")
    assert main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "Warning: no test reaches changed module pkg/lonely.py" in out
    assert "Selection confidence: Medium" in out


def test_cli_safe_select_all_message(sample_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_tree(sample_repo, {"data.json": "{}\n"})
    assert main(["--safe", "--list"]) == 0
    out = capsys.readouterr().out
    assert "Selected: all tests" in out


def _make_repo(tmp_path: Path) -> Path:
    write_tree(tmp_path, SAMPLE_PROJECT)
    git_repo(tmp_path)
    return tmp_path


def test_cli_runs_pytest_on_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    (repo / "pkg/top.py").write_text("import pkg.mid\n\ndef top() -> int:\n    return 3\n")
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Running 2 of 4 tests..." in out
    assert "2 passed" in out
    assert "Skipped: 2 (not selected)" in out
    assert "Selection confidence: High" in out


def test_cli_propagates_pytest_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    (repo / "pkg/core.py").write_text("def core() -> int:\n    return 42\n")
    assert main([]) != 0
    out = capsys.readouterr().out
    assert "failed" in out


def test_file_at_ref_returns_content_and_none(sample_repo: Path) -> None:
    original = (sample_repo / "pkg/core.py").read_text()
    (sample_repo / "pkg/core.py").write_text("def core() -> int:\n    return 2\n")
    assert file_at_ref(sample_repo, "pkg/core.py") == original
    assert file_at_ref(sample_repo, "pkg/nothing.py") is None


def test_cli_narrows_a_changed_conftest_to_the_fixtures_that_moved(
    sample_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The end-to-end path: git supplies the old content, selection diffs it."""
    write_tree(
        sample_repo,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "\n"
                "@pytest.fixture\n"
                "def hot():\n"
                "    return 1\n"
                "\n"
                "\n"
                "@pytest.fixture\n"
                "def cold():\n"
                "    return 2\n"
            ),
            "tests/test_hot.py": "def test_hot(hot) -> None:\n    assert hot\n",
            "tests/test_cold.py": "def test_cold(cold) -> None:\n    assert cold\n",
        },
    )
    git(sample_repo, "add", "-A")
    git(sample_repo, "commit", "-q", "-m", "fixtures")

    conftest = sample_repo / "tests/conftest.py"
    conftest.write_text(conftest.read_text().replace("    return 1\n", "    return 11\n"))

    assert main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "requests changed fixture hot from tests/conftest.py" in out
    assert "tests/test_cold.py" not in out


def test_cli_changed_conftest_uses_the_ref_as_the_baseline(
    sample_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With an explicit revision, the old content comes from that revision."""
    write_tree(
        sample_repo,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "\n"
                "@pytest.fixture\n"
                "def hot():\n"
                "    return 1\n"
                "\n"
                "\n"
                "@pytest.fixture\n"
                "def cold():\n"
                "    return 2\n"
            ),
            "tests/test_hot.py": "def test_hot(hot) -> None:\n    assert hot\n",
            "tests/test_cold.py": "def test_cold(cold) -> None:\n    assert cold\n",
        },
    )
    git(sample_repo, "add", "-A")
    git(sample_repo, "commit", "-q", "-m", "fixtures")

    conftest = sample_repo / "tests/conftest.py"
    conftest.write_text(conftest.read_text().replace("    return 2\n", "    return 22\n"))
    git(sample_repo, "add", "-A")
    git(sample_repo, "commit", "-q", "-m", "cold moved")

    assert main(["HEAD~1", "--list"]) == 0
    out = capsys.readouterr().out
    assert "requests changed fixture cold from tests/conftest.py" in out
    assert "tests/test_hot.py" not in out
