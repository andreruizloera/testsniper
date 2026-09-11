"""Symbol narrowing carried across the import graph, not stopped at hop one.

Every case here is end to end, through the real CLI on a real git repository,
because all three are about what the SELECTION is and not about what any one
function returns. Each of them fails on the version of testsniper that read a
changed module's own diff and nothing else.

Two of the three are UNDER-selections, which is the failure mode this tool
exists to prevent: the run is green, the suite is not, and nothing says so.
The tests therefore assert the real failure as well as the selection, so a
future change that makes the selection right by accident and the run wrong
cannot pass them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import git_repo, write_tree

UP = '''"""The module that changes."""


def alpha() -> int:
    return 1


def beta() -> int:
    return 2
'''

MID = '''"""Downstream of up, with one function per upstream symbol."""

from up import alpha, beta


def uses_alpha() -> int:
    return alpha()


def uses_beta() -> int:
    return beta()
'''

TEST_MID = """from mid import uses_alpha, uses_beta


def test_alpha():
    assert uses_alpha() == 1


def test_beta():
    assert uses_beta() == 2
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


def _two_hop_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    write_tree(repo, {"up.py": UP, "mid.py": MID, "tests/test_mid.py": TEST_MID})
    git_repo(repo)
    return repo


def test_narrowing_carries_past_the_first_import_hop(tmp_path: Path) -> None:
    """Only the test whose path reaches the changed symbol is selected.

    Before, mid.py had no diff of its own, so every symbol in it stayed
    affected and both tests ran. uses_beta cannot see a change to alpha.
    """
    repo = _two_hop_repo(tmp_path)
    (repo / "up.py").write_text(UP.replace("return 1", "value = 1\n    return value"))

    out = _run(repo, "--nodes", "--list").stdout
    assert "would run 1 of 2 tests" in out
    assert "test_alpha" in out
    assert "test_beta" not in out


def test_a_module_that_is_changed_and_downstream_keeps_both_answers(tmp_path: Path) -> None:
    """The under-selection: a narrow own-diff answer used to REPLACE the wide one.

    up.alpha really breaks, and mid.py is independently edited in a function
    that has nothing to do with it. mid.py's own diff names uses_beta, and that
    answer used to be the whole answer, so test_alpha was deselected and the
    run passed while the suite failed.
    """
    repo = _two_hop_repo(tmp_path)
    (repo / "up.py").write_text(UP.replace("return 1", "return 99"))
    (repo / "mid.py").write_text(MID.replace("return beta()", "result = beta()\n    return result"))

    out = _run(repo, "--nodes", "--list").stdout
    assert "would run 2 of 2 tests" in out
    assert "test_alpha" in out
    assert "test_beta" in out

    # The selection is only half the claim. The reason test_alpha must run is
    # that it fails, so a run that selects it has to be red.
    run = _run(repo, "--nodes")
    assert run.returncode != 0
    assert "1 failed" in run.stdout
    assert _pytest(repo, "-q").returncode != 0


def test_an_affected_package_init_is_not_narrowed_past(tmp_path: Path) -> None:
    """Importing a submodule runs the package __init__ first.

    The test file reaches the change only that way: it imports pkg.sub, which
    imports nothing, while the changed pkg/__init__.py sets the environment
    both of them read. No name bound by ``from pkg.sub import label`` stands
    for that side effect, so narrowing used to drop the only test in the file
    and report a green run against a failing suite.
    """
    repo = tmp_path / "proj"
    init = 'import os\n\nSTAMP = "v1"\nos.environ.setdefault("PKG_STAMP", STAMP)\n'
    write_tree(
        repo,
        {
            "pkg/__init__.py": init,
            "pkg/sub.py": (
                'import os\n\n\ndef label() -> str:\n    return os.environ["PKG_STAMP"]\n'
            ),
            "tests/test_x.py": (
                'from pkg.sub import label\n\n\ndef test_label():\n    assert label() == "v1"\n'
            ),
        },
    )
    git_repo(repo)
    (repo / "pkg" / "__init__.py").write_text(init.replace("v1", "v2"))

    out = _run(repo, "--nodes", "--list").stdout
    assert "would run 1 of 1 tests" in out
    assert "its package pkg is affected and runs on import" in out
    assert _pytest(repo, "-q").returncode != 0


def test_a_reexporting_package_init_is_still_narrowed(tmp_path: Path) -> None:
    """The control for the test above, and the reason it is not a blanket rule.

    Here pkg/__init__.py re-exports from the changed submodule, which is the
    common layout. Its module-level code is inert, so its symbols are readable
    and importing a sibling submodule through it changes nothing. Blocking on
    every affected parent package would make this whole repository
    unnarrowable.
    """
    repo = tmp_path / "proj"
    write_tree(
        repo,
        {
            "pkg/__init__.py": 'from pkg.changed import build\n\n__all__ = ["build"]\n',
            "pkg/changed.py": (
                "def build() -> int:\n    return 1\n\n\ndef other() -> int:\n    return 2\n"
            ),
            "pkg/quiet.py": "def quiet() -> int:\n    return 3\n",
            "tests/test_quiet.py": (
                "from pkg.quiet import quiet\n\n\ndef test_quiet():\n    assert quiet() == 3\n"
            ),
            "tests/test_build.py": (
                "from pkg.changed import build\n\n\ndef test_build():\n    assert build() == 1\n"
            ),
        },
    )
    git_repo(repo)
    (repo / "pkg" / "changed.py").write_text(
        "def build() -> int:\n    value = 1\n    return value\n\n\n"
        "def other() -> int:\n    return 2\n"
    )

    out = _run(repo, "--nodes", "--list").stdout
    assert "runs on import" not in out
    assert "would run 1 of 2 tests" in out
    assert "test_build" in out
    # tests/test_quiet.py is still selected at FILE level, and correctly so:
    # it imports pkg, whose __init__ is in the closure. Node narrowing is what
    # empties it, because pkg.quiet reads nothing that moved.
    assert "tests/test_quiet.py  [distance 2] imports it transitively" in out
    assert "0 of 1 tests" in out
    assert "test_quiet\n" not in out


def test_an_import_cycle_keeps_the_wide_answer(tmp_path: Path) -> None:
    """Cycles have no dependency order, so their modules stay fully affected.

    Refusing here is the same choice every other unreadable construct gets,
    and the note is what keeps the refusal from being invisible.
    """
    repo = tmp_path / "proj"
    write_tree(
        repo,
        {
            "base.py": "def seed() -> int:\n    return 1\n",
            "a.py": (
                "from base import seed\n\n\ndef a_one() -> int:\n"
                "    import b\n\n    return seed() + b.b_one()\n"
            ),
            "b.py": (
                "import a\n\n\ndef b_one() -> int:\n    return 1\n\n\n"
                "def b_two() -> int:\n    return a.a_one()\n"
            ),
            "tests/test_cycle.py": (
                "from b import b_one\n\n\ndef test_b_one():\n    assert b_one() == 1\n"
            ),
        },
    )
    git_repo(repo)
    (repo / "base.py").write_text("def seed() -> int:\n    value = 1\n    return value\n")

    out = _run(repo, "--nodes", "--list").stdout
    assert "import cycle" in out
    assert "symbol narrowing gave up" in out


def test_the_reason_a_narrowing_did_not_happen_is_printed(tmp_path: Path) -> None:
    """A blocked module used to widen the selection and say nothing about it."""
    repo = tmp_path / "proj"
    write_tree(
        repo,
        {
            "up.py": UP,
            "tests/test_up.py": (
                "from up import alpha\n\n\ndef test_a():\n    assert alpha() == 1\n"
            ),
        },
    )
    git_repo(repo)
    (repo / "up.py").write_text(UP + "\nSTATE = alpha()\n")

    out = _run(repo, "--nodes", "--list").stdout
    assert "symbol narrowing gave up on 1 module(s)" in out
    assert "module-level code in up.py changed; it runs on import" in out
