"""File-level selection when the conftest.py itself is what changed.

Before this, a changed conftest selected every test file under it and turned
narrowing off for all of them, because the graph could only read its fixtures
at their new content. Given the old content, the same fixture graph says which
of them the diff actually moved, and selection is the ordinary fixture answer.

``select`` takes an ``old_source`` callback and nothing else about revisions,
so these tests supply the previous content directly. The git side of it is
covered in test_cli.py.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.config import load_config
from testsniper.nodes import narrow_selection
from testsniper.scanner import scan_repo
from testsniper.selector import Selection, select

CONFTEST = (
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
)

PROJECT: dict[str, str] = {
    "pyproject.toml": (
        "[project]\n"
        'name = "sample"\n'
        'version = "0.1.0"\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
    ),
    "tests/conftest.py": CONFTEST,
    "tests/test_asks.py": (
        "def test_asks(hot) -> None:\n    assert hot == 1\n"
        "\n\ndef test_other() -> None:\n    assert True\n"
    ),
    "tests/test_quiet.py": "def test_quiet(cold) -> None:\n    assert cold == 2\n",
}


def _select(
    root: Path,
    new_conftest: str,
    old_conftest: str | None = CONFTEST,
    mode: str = "default",
    files: dict[str, str] | None = None,
) -> Selection:
    write_tree(root, {**PROJECT, **(files or {}), "tests/conftest.py": new_conftest})
    return select(
        root,
        ["tests/conftest.py"],
        mode,  # type: ignore[arg-type]
        load_config(root),
        old_source=lambda rel: old_conftest if rel == "tests/conftest.py" else None,
    )


def _paths(sel: Selection) -> list[str]:
    return [t.relpath for t in sel.tests]


def _picked(sel: Selection, relpath: str):
    return next(t for t in sel.tests if t.relpath == relpath)


def test_only_the_files_that_ask_for_the_changed_fixture_are_selected(tmp_path: Path) -> None:
    new = CONFTEST.replace("def hot():\n    return 1\n", "def hot():\n    return 11\n")
    sel = _select(tmp_path, new)
    assert _paths(sel) == ["tests/test_asks.py"]
    assert _picked(sel, "tests/test_asks.py").reason == (
        "requests changed fixture hot from tests/conftest.py"
    )
    assert _picked(sel, "tests/test_asks.py").channel == "fixture"


def test_the_selected_file_is_still_narrowed(tmp_path: Path) -> None:
    """The old rule ran every test in the subtree. This one narrows inside it."""
    new = CONFTEST.replace("def hot():\n    return 1\n", "def hot():\n    return 11\n")
    sel = _select(tmp_path, new)
    infos = scan_repo(tmp_path)
    nodes = narrow_selection(tmp_path, sel, infos)
    file_nodes = nodes["tests/test_asks.py"]
    assert file_nodes.narrowed
    assert {name for _, name in file_nodes.selected} == {"test_asks"}


def test_a_change_that_moves_no_fixture_selects_nothing(tmp_path: Path) -> None:
    new = CONFTEST.replace("    return 1\n", "    # unchanged behavior\n    return 1\n")
    sel = _select(tmp_path, new)
    assert _paths(sel) == []
    assert sel.confidence == "High"


def test_an_autouse_change_still_takes_the_whole_subtree(tmp_path: Path) -> None:
    old = CONFTEST + "\n\n@pytest.fixture(autouse=True)\ndef _always():\n    return 1\n"
    new = old.replace("def _always():\n    return 1\n", "def _always():\n    return 2\n")
    sel = _select(tmp_path, new, old)
    assert _paths(sel) == ["tests/test_asks.py", "tests/test_quiet.py"]
    reason = "autouse fixture _always in tests/conftest.py reaches the change"
    assert _picked(sel, "tests/test_quiet.py").whole_file == reason


def test_a_new_conftest_takes_the_whole_subtree(tmp_path: Path) -> None:
    """Nothing to diff against, so nothing narrower is knowable."""
    sel = _select(tmp_path, CONFTEST, None)
    assert _paths(sel) == ["tests/test_asks.py", "tests/test_quiet.py"]
    reason = "tests/conftest.py has no previous content to compare against"
    assert _picked(sel, "tests/test_asks.py").whole_file == reason


def test_without_an_old_source_callback_the_old_rule_applies(tmp_path: Path) -> None:
    """select() is usable without git, and then it cannot narrow this."""
    write_tree(tmp_path, PROJECT)
    sel = select(tmp_path, ["tests/conftest.py"], "default", load_config(tmp_path))
    assert _paths(sel) == ["tests/test_asks.py", "tests/test_quiet.py"]
    assert _picked(sel, "tests/test_asks.py").whole_file == "under changed tests/conftest.py"
    assert "tests/conftest.py changed; selecting its whole subtree" in sel.notes


def test_a_deleted_conftest_takes_the_whole_subtree(tmp_path: Path) -> None:
    """It is not on disk to be indexed, so there are no fixtures to diff."""
    write_tree(tmp_path, PROJECT)
    (tmp_path / "tests" / "conftest.py").unlink()
    sel = select(
        tmp_path,
        ["tests/conftest.py"],
        "default",
        load_config(tmp_path),
        old_source=lambda rel: CONFTEST,
    )
    assert _paths(sel) == ["tests/test_asks.py", "tests/test_quiet.py"]
    assert _picked(sel, "tests/test_asks.py").whole_file == "under changed tests/conftest.py"


def test_safe_mode_takes_the_subtree_when_any_fixture_moved(tmp_path: Path) -> None:
    new = CONFTEST.replace("def hot():\n    return 1\n", "def hot():\n    return 11\n")
    sel = _select(tmp_path, new, mode="safe")
    assert _paths(sel) == ["tests/test_asks.py", "tests/test_quiet.py"]
    assert sel.notes == [
        "tests/conftest.py is changed through hot; safe mode selects its whole subtree"
    ]


def test_aggressive_mode_still_ignores_a_changed_conftest(tmp_path: Path) -> None:
    new = CONFTEST.replace("def hot():\n    return 1\n", "def hot():\n    return 11\n")
    sel = _select(tmp_path, new, mode="aggressive")
    assert _paths(sel) == []
    assert sel.confidence == "Low"
    assert any("changed conftest.py ignored" in r for r in sel.confidence_reasons)


def test_a_changed_conftest_and_a_changed_module_combine(tmp_path: Path) -> None:
    """One fixture moved in the diff, another reads a module that changed."""
    files = {
        "pkg/__init__.py": "",
        "pkg/changed.py": "def build() -> int:\n    return 1\n",
    }
    old = (
        "import pytest\n"
        "\n"
        "from pkg.changed import build\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def hot():\n"
        "    return 1\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def cold():\n"
        "    return build()\n"
    )
    new = old.replace("def hot():\n    return 1\n", "def hot():\n    return 11\n")
    write_tree(tmp_path, {**PROJECT, **files, "tests/conftest.py": new})
    sel = select(
        tmp_path,
        ["tests/conftest.py", "pkg/changed.py"],
        "default",  # type: ignore[arg-type]
        load_config(tmp_path),
        old_source=lambda rel: old if rel == "tests/conftest.py" else None,
    )
    assert _paths(sel) == ["tests/test_asks.py", "tests/test_quiet.py"]
    assert _picked(sel, "tests/test_asks.py").reason == (
        "requests changed fixture hot from tests/conftest.py"
    )
    assert _picked(sel, "tests/test_quiet.py").reason == (
        "requests changed fixture cold from tests/conftest.py"
    )
