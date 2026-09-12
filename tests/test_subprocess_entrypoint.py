"""A test that RUNS the project instead of importing it.

This is an UNDER-selection, the failure mode this tool exists to prevent,
and it was found by running testsniper on testsniper. A CLI end-to-end test
does not import the code it exercises; it starts a process. The import
graph sees nothing, so the test was never selected, and a change that broke
the command line produced a green run against a red suite.

Every case here is end to end through the real CLI on a real git
repository, and the two under-selection cases assert the real pytest
FAILURE as well as the selection. Selecting the right test for the wrong
reason is not enough: a future change that gets the selection right and
the run wrong has to fail these.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import git, git_repo, write_tree

CLI = '''"""The code the command line runs."""


def greeting() -> str:
    return "hello"


def main() -> int:
    print(greeting())
    return 0
'''

MAIN = '''"""Run as `python -m pkg`."""

import sys

from pkg.cli import main

if __name__ == "__main__":
    sys.exit(main())
'''

LONELY = '''"""Nothing reaches this, and it reaches nothing."""


def lonely() -> int:
    return 99
'''

# The test under test: it imports NOTHING from pkg. The only connection is
# the string "pkg" inside the argument vector.
TEST_SUBPROCESS = """import subprocess
import sys


def test_the_command_line_greets():
    proc = subprocess.run(
        [sys.executable, "-m", "pkg"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.stdout.strip() == "hello"
"""

TEST_LONELY = """from pkg.lonely import lonely


def test_lonely():
    assert lonely() == 99
"""


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "testsniper", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _pytest(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _cli_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    write_tree(
        repo,
        {
            "pkg/__init__.py": "",
            "pkg/cli.py": CLI,
            "pkg/__main__.py": MAIN,
            "pkg/lonely.py": LONELY,
            "tests/test_subprocess.py": TEST_SUBPROCESS,
            "tests/test_lonely.py": TEST_LONELY,
        },
    )
    git_repo(repo)
    return repo


def test_a_subprocess_only_test_is_selected_when_the_command_changes(tmp_path: Path) -> None:
    """The whole point. Nothing imports pkg.cli from the tests.

    Before this landed, the selection was empty: no test file imports
    pkg.cli, and `python -m pkg` is not an import statement.
    """
    repo = _cli_repo(tmp_path)
    (repo / "pkg" / "cli.py").write_text(CLI.replace('return "hello"', 'return "goodbye"'))

    result = _run(repo, "--list")
    assert result.returncode == 0, result.stderr
    assert "tests/test_subprocess.py" in result.stdout
    assert "tests/test_lonely.py" not in result.stdout


def test_the_selected_run_is_red_when_the_command_really_breaks(tmp_path: Path) -> None:
    """Selection is half the claim; the reason to run it is that it fails."""
    repo = _cli_repo(tmp_path)
    (repo / "pkg" / "cli.py").write_text(CLI.replace('return "hello"', 'return "goodbye"'))

    run = _run(repo)
    assert run.returncode != 0
    assert "1 failed" in run.stdout
    # The suite agrees, so the selection is not red for a reason of its own.
    assert _pytest(repo, "-q").returncode != 0


def test_node_narrowing_reaches_the_subprocess_test_function(tmp_path: Path) -> None:
    """The taint has to survive down to the individual test function."""
    repo = _cli_repo(tmp_path)
    (repo / "pkg" / "cli.py").write_text(CLI.replace('return "hello"', 'return "goodbye"'))

    out = _run(repo, "--nodes", "--list").stdout
    assert "test_the_command_line_greets" in out
    assert "test_lonely" not in out


def test_a_change_the_command_cannot_reach_does_not_select_it(tmp_path: Path) -> None:
    """The control. Without it, this feature could be 'select everything'.

    pkg/lonely.py is not reachable from the command line, so the subprocess
    test must stay deselected while the test that does import it runs.
    """
    repo = _cli_repo(tmp_path)
    (repo / "pkg" / "lonely.py").write_text(LONELY.replace("return 99", "return 100"))

    out = _run(repo, "--list").stdout
    assert "tests/test_lonely.py" in out
    assert "tests/test_subprocess.py" not in out


def test_a_subprocess_to_an_unrelated_module_selects_nothing(tmp_path: Path) -> None:
    """`python -m pytest` in a test file must not bind that file to the project."""
    repo = _cli_repo(tmp_path)
    (repo / "tests" / "test_subprocess.py").write_text(
        TEST_SUBPROCESS.replace('"-m", "pkg"', '"-m", "this_is_not_in_the_repo"')
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "point the subprocess somewhere else")
    (repo / "pkg" / "cli.py").write_text(CLI.replace('return "hello"', 'return "goodbye"'))

    out = _run(repo, "--list").stdout
    assert "tests/test_subprocess.py" not in out


def test_the_reason_says_the_test_runs_the_module_rather_than_imports_it(tmp_path: Path) -> None:
    """`python -m pkg` reaches pkg.cli through pkg/__main__.py, two steps out.

    Before the reason was told apart, this line read "imports it
    transitively" about a file whose only import is `subprocess`.
    """
    repo = _cli_repo(tmp_path)
    (repo / "pkg" / "cli.py").write_text(CLI.replace('return "hello"', 'return "goodbye"'))

    out = _run(repo, "--list").stdout
    expected = (
        "tests/test_subprocess.py  [distance 2] runs it in a subprocess, transitively (distance 2)"
    )
    assert expected in out
