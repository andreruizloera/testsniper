"""A test that runs the project through its CONSOLE SCRIPT.

`subprocess.run(["greet"])` imports nothing and names no module. The only
thing connecting it to `pkg.cli` is one line of packaging metadata,
`greet = "pkg.cli:main"`, so before this was read, breaking `pkg.cli`
selected none of these tests while the suite went red. That is an
UNDER-selection, the failure mode this tool exists to prevent.

The script has to really run, so each repository gets the wrapper an
installer generates for that line, on PATH, outside the repository. Every
case is end to end through the real CLI or plugin, the under-selection
cases assert the real pytest FAILURES rather than only the selection, and
each way the analysis can reach a script test (the test itself, a helper
module it imports, a conftest fixture) has its own case with a control next
to it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import git_repo, write_tree

PYPROJECT = (
    '[project]\nname = "greetpkg"\nversion = "0.1.0"\n\n[project.scripts]\ngreet = "pkg.cli:main"\n'
)

CLI = '''"""The code the console script runs."""


def greeting() -> str:
    return "hello"


def main() -> int:
    print(greeting())
    return 0
'''

LONELY = '''"""Nothing the script runs reaches this."""


def lonely() -> int:
    return 99
'''

SHELL = '''"""A helper module: tests import this instead of starting the script."""

import subprocess


def run_greet() -> str:
    proc = subprocess.run(["greet"], capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def banner() -> str:
    return "== greet =="
'''

# The test under test imports NOTHING from pkg.
TEST_SCRIPT = """import subprocess


def test_the_script_greets():
    proc = subprocess.run(["greet"], capture_output=True, text=True, check=False)
    assert proc.stdout.strip() == "hello"
"""

TEST_SHELL = """from pkg.shell import banner, run_greet


def test_run_greet():
    assert run_greet() == "hello"


def test_banner():
    assert banner() == "== greet =="
"""

FIXTURE_CONFTEST = """import subprocess

import pytest


@pytest.fixture
def greeting():
    proc = subprocess.run(["greet"], capture_output=True, text=True, check=False)
    return proc.stdout.strip()
"""

TEST_FIXTURE = """def test_greeting_fixture(greeting):
    assert greeting == "hello"


def test_plain():
    assert 1 + 1 == 2
"""

TEST_LONELY = """from pkg.lonely import lonely


def test_lonely():
    assert lonely() == 99
"""

# What pip and uv write for `greet = "pkg.cli:main"`, minus their argv[0]
# rewriting, which this project does not read.
WRAPPER = """#!{python}
import sys

from pkg.cli import main

if __name__ == "__main__":
    sys.exit(main())
"""


def _project(tmp_path: Path, pyproject: str = PYPROJECT) -> Path:
    repo = tmp_path / "proj"
    write_tree(
        repo,
        {
            "pyproject.toml": pyproject,
            "pkg/__init__.py": "",
            "pkg/cli.py": CLI,
            "pkg/lonely.py": LONELY,
            "pkg/shell.py": SHELL,
            "tests/test_script.py": TEST_SCRIPT,
            "tests/test_shell.py": TEST_SHELL,
            "tests/test_lonely.py": TEST_LONELY,
            "tests/fixtured/conftest.py": FIXTURE_CONFTEST,
            "tests/fixtured/test_fixture.py": TEST_FIXTURE,
        },
    )
    git_repo(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "greet"
    script.write_text(WRAPPER.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o755)
    return repo


def _env(repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{repo.parent / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = str(repo)
    return env


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "testsniper", *args],
        cwd=repo,
        env=_env(repo),
        capture_output=True,
        text=True,
        check=False,
    )


def _pytest(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=repo,
        env=_env(repo),
        capture_output=True,
        text=True,
        check=False,
    )


def _failed(output: str) -> set[str]:
    return {line.split(" - ")[0] for line in output.splitlines() if line.startswith("FAILED ")}


def _break_the_script(repo: Path) -> None:
    (repo / "pkg" / "cli.py").write_text(CLI.replace('return "hello"', 'return "goodbye"'))


def test_the_wrapper_really_runs_the_script(tmp_path: Path) -> None:
    """Every other case depends on this, so it is checked rather than assumed."""
    repo = _project(tmp_path)
    result = _pytest(repo, "-q")
    assert result.returncode == 0, result.stdout
    assert "6 passed" in result.stdout


def test_a_script_only_test_is_selected_when_the_script_module_changes(tmp_path: Path) -> None:
    repo = _project(tmp_path)
    _break_the_script(repo)

    result = _run(repo, "--list")
    assert result.returncode == 0, result.stderr
    assert "tests/test_script.py" in result.stdout
    assert "tests/test_lonely.py" not in result.stdout
    assert "no test reaches changed module" not in result.stdout


def test_the_selected_run_fails_exactly_where_the_suite_fails(tmp_path: Path) -> None:
    """Selection is half the claim; the reason to run it is that it fails."""
    repo = _project(tmp_path)
    _break_the_script(repo)

    run = _run(repo)
    suite = _pytest(repo, "-q", "-rf")
    assert run.returncode != 0
    assert suite.returncode != 0
    assert _failed(suite.stdout) == {
        "FAILED tests/test_script.py::test_the_script_greets",
        "FAILED tests/test_shell.py::test_run_greet",
        "FAILED tests/fixtured/test_fixture.py::test_greeting_fixture",
    }
    assert _failed(run.stdout) == _failed(suite.stdout)


def test_node_narrowing_reaches_the_test_that_starts_the_script(tmp_path: Path) -> None:
    repo = _project(tmp_path)
    _break_the_script(repo)

    out = _run(repo, "--nodes", "--list").stdout
    assert "test_the_script_greets" in out
    assert "test_lonely" not in out


def test_symbol_narrowing_follows_a_helper_that_starts_the_script(tmp_path: Path) -> None:
    """`run_greet` reaches the script and `banner` does not, in one module."""
    repo = _project(tmp_path)
    _break_the_script(repo)

    out = _run(repo, "--nodes", "--list").stdout
    assert "test_run_greet" in out
    assert "test_banner" not in out


def test_a_conftest_fixture_that_starts_the_script_selects_its_users(tmp_path: Path) -> None:
    repo = _project(tmp_path)
    _break_the_script(repo)

    out = _run(repo, "--nodes", "--list").stdout
    assert "test_greeting_fixture" in out
    assert "test_plain" not in out


def test_a_change_the_script_cannot_reach_selects_none_of_it(tmp_path: Path) -> None:
    """The control. Without it, this feature could be 'select everything'."""
    repo = _project(tmp_path)
    (repo / "pkg" / "lonely.py").write_text(LONELY.replace("return 99", "return 100"))

    out = _run(repo, "--list").stdout
    assert "tests/test_lonely.py" in out
    assert "tests/test_script.py" not in out
    assert "tests/test_shell.py" not in out
    assert "tests/fixtured/test_fixture.py" not in out


def test_without_the_metadata_the_program_name_means_nothing(tmp_path: Path) -> None:
    """The edge comes from `[project.scripts]`, not from the name `greet`."""
    repo = _project(tmp_path, pyproject='[project]\nname = "greetpkg"\nversion = "0.1.0"\n')
    _break_the_script(repo)

    out = _run(repo, "--list").stdout
    assert "tests/test_script.py" not in out
    assert "no test reaches changed module pkg/cli.py" in out


def test_the_pytest_plugin_runs_the_same_failures(tmp_path: Path) -> None:
    repo = _project(tmp_path)
    _break_the_script(repo)

    plugin = _pytest(repo, "-q", "-rf", "--testsniper")
    suite = _pytest(repo, "-q", "-rf")
    assert plugin.returncode != 0
    assert len(_failed(suite.stdout)) == 3
    assert _failed(plugin.stdout) == _failed(suite.stdout)
    # test_banner, test_plain and test_lonely, which is what makes the equal
    # failure sets a selection rather than a full run.
    assert "3 failed, 3 deselected" in plugin.stdout


def test_the_reason_says_runs_for_a_test_that_only_starts_the_script(tmp_path: Path) -> None:
    """A reason reading "imports" about a test that imports nothing is false.

    tests/test_shell.py is the control: it reaches the same change one step
    further out, and its own step is an import of the helper, so it keeps
    the import wording.
    """
    repo = _project(tmp_path)
    _break_the_script(repo)

    out = _run(repo, "--list").stdout
    assert "tests/test_script.py  [distance 1] runs a changed module in a subprocess" in out
    assert "tests/test_shell.py  [distance 2] imports it transitively (distance 2)" in out
