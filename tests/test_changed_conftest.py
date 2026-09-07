"""Unit tests for reading a CHANGED conftest.py through its own diff.

The other fixture-graph tests ask which fixtures READ something affected.
These ask the other question: the conftest itself is what changed, so its
previous content decides which of its fixtures moved and which did not.

Every case here goes through ``analyze_conftests`` with ``old_sources``, the
same entry point selection uses, rather than through the private differ.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.fixtures import analyze_conftests
from testsniper.scanner import scan_repo

BASE: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/one.py": "def one() -> int:\n    return 1\n",
    "pkg/two.py": "def two() -> int:\n    return 2\n",
}

CONFTEST = (
    "import pytest\n"
    "\n"
    "from pkg.one import one\n"
    "\n"
    "SIZE = 3\n"
    "\n"
    "\n"
    "def _helper():\n"
    "    return one()\n"
    "\n"
    "\n"
    "@pytest.fixture\n"
    "def alpha():\n"
    "    return _helper()\n"
    "\n"
    "\n"
    "@pytest.fixture\n"
    "def beta():\n"
    "    return SIZE\n"
)


def _verdict(root: Path, new: str, old: str | None, chain: list[str] | None = None):
    """Analyze tests/conftest.py at content ``new``, diffed against ``old``."""
    write_tree(root, {**BASE, "tests/conftest.py": new})
    infos = scan_repo(root)
    return analyze_conftests(
        root,
        chain or ["tests/conftest.py"],
        set(),
        infos,
        old_sources={"tests/conftest.py": old},
    )


def test_only_the_fixture_whose_body_changed_is_tainted(tmp_path: Path) -> None:
    new = CONFTEST.replace("    return SIZE\n", "    return SIZE + 1\n")
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset({"beta"})


def test_a_changed_helper_taints_the_fixture_that_calls_it(tmp_path: Path) -> None:
    """The diff moved a plain function, not a fixture; the fixture inherits it."""
    new = CONFTEST.replace("    return one()\n", "    return one() * 2\n")
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset({"alpha"})


def test_an_unchanged_conftest_taints_nothing(tmp_path: Path) -> None:
    verdict = _verdict(tmp_path, CONFTEST, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset()


def test_a_comment_only_change_taints_nothing(tmp_path: Path) -> None:
    """Definitions are compared as parsed syntax, and a comment is not in it."""
    new = CONFTEST.replace("    return SIZE\n", "    # explain the size\n    return SIZE\n")
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset()


def test_a_docstring_change_does_taint(tmp_path: Path) -> None:
    """Under --doctest-modules pytest collects doctests out of a conftest, so
    a docstring in one can itself be a test."""
    new = CONFTEST.replace("def beta():\n", 'def beta():\n    """Now documented."""\n')
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset({"beta"})


def test_a_new_fixture_is_tainted(tmp_path: Path) -> None:
    new = CONFTEST + "\n\n@pytest.fixture\ndef gamma():\n    return 9\n"
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset({"gamma"})


def test_a_deleted_fixture_is_tainted_by_name(tmp_path: Path) -> None:
    """Its node is gone, so no graph walk can reach it; the name is enough."""
    new = CONFTEST.replace("\n\n@pytest.fixture\ndef beta():\n    return SIZE\n", "")
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset({"beta"})


def test_a_renamed_fixture_taints_both_names(tmp_path: Path) -> None:
    new = CONFTEST.replace("def beta():", "def betta():")
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset({"beta", "betta"})


def test_a_changed_import_taints_what_reads_it(tmp_path: Path) -> None:
    """The fixture body is untouched; the name under it now means something else."""
    new = CONFTEST.replace("from pkg.one import one\n", "from pkg.two import two as one\n")
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block is None
    assert verdict.tainted == frozenset({"alpha"})


def test_module_level_code_changing_blocks_the_subtree(tmp_path: Path) -> None:
    new = CONFTEST.replace("SIZE = 3\n", "SIZE = 4\n")
    verdict = _verdict(tmp_path, new, CONFTEST)
    assert verdict.block == "module-level code in tests/conftest.py changed; it runs on import"


def test_module_level_code_reading_a_changed_definition_blocks(tmp_path: Path) -> None:
    """The statement is identical, but what it calls is not."""
    old = CONFTEST + "\n\nREADY = _helper()\n"
    new = old.replace("    return one()\n", "    return one() * 2\n")
    verdict = _verdict(tmp_path, new, old)
    assert verdict.block == (
        "module-level code in tests/conftest.py reads something the diff changed"
    )


def test_a_changed_autouse_fixture_blocks_the_subtree(tmp_path: Path) -> None:
    old = CONFTEST + "\n\n@pytest.fixture(autouse=True)\ndef _always():\n    return 1\n"
    new = old.replace("def _always():\n    return 1\n", "def _always():\n    return 2\n")
    verdict = _verdict(tmp_path, new, old)
    assert verdict.block == "autouse fixture _always in tests/conftest.py reaches the change"


def test_a_deleted_autouse_fixture_blocks_the_subtree(tmp_path: Path) -> None:
    old = CONFTEST + "\n\n@pytest.fixture(autouse=True)\ndef _always():\n    return 1\n"
    verdict = _verdict(tmp_path, CONFTEST, old)
    assert verdict.block == "autouse fixture _always was removed from tests/conftest.py"


def test_a_changed_hook_blocks_the_subtree(tmp_path: Path) -> None:
    old = CONFTEST + "\n\ndef pytest_collection_modifyitems(items):\n    return None\n"
    new = old.replace("    return None\n", "    items.reverse()\n")
    verdict = _verdict(tmp_path, new, old)
    assert verdict.block == (
        "hook pytest_collection_modifyitems in tests/conftest.py uses an affected import"
    )


def test_a_deleted_hook_blocks_the_subtree(tmp_path: Path) -> None:
    old = CONFTEST + "\n\ndef pytest_collection_modifyitems(items):\n    return None\n"
    verdict = _verdict(tmp_path, CONFTEST, old)
    assert verdict.block == (
        "hook pytest_collection_modifyitems was removed from tests/conftest.py"
    )


def test_a_changed_star_import_blocks_the_subtree(tmp_path: Path) -> None:
    old = "import pytest\n\nfrom pkg.one import *\n\n\n@pytest.fixture\ndef a():\n    return 1\n"
    new = old.replace("from pkg.one import *", "from pkg.two import *")
    verdict = _verdict(tmp_path, new, old)
    assert verdict.block == "a star import in tests/conftest.py changed"


def test_no_previous_content_blocks_the_subtree(tmp_path: Path) -> None:
    """A conftest git has never seen: every fixture in it is new."""
    verdict = _verdict(tmp_path, CONFTEST, None)
    assert verdict.block == ("tests/conftest.py has no previous content to compare against")


def test_unparseable_previous_content_blocks_the_subtree(tmp_path: Path) -> None:
    verdict = _verdict(tmp_path, CONFTEST, "def broken(:\n")
    assert verdict.block == "the previous content of tests/conftest.py could not be parsed"


def test_a_changed_outer_conftest_is_read_through_the_whole_chain(tmp_path: Path) -> None:
    """The change is in the root conftest; the inner one is untouched."""
    outer = "import pytest\n\n\n@pytest.fixture\ndef shared():\n    return 1\n"
    inner = "import pytest\n\n\n@pytest.fixture\ndef local(shared):\n    return shared\n"
    write_tree(tmp_path, {**BASE, "conftest.py": outer, "tests/conftest.py": inner})
    infos = scan_repo(tmp_path)
    verdict = analyze_conftests(
        tmp_path,
        ["conftest.py", "tests/conftest.py"],
        set(),
        infos,
        old_sources={"conftest.py": outer.replace("    return 1\n", "    return 2\n")},
    )
    assert verdict.block is None
    # The inner fixture requests the changed one, so it carries the change on.
    assert verdict.tainted == frozenset({"shared", "local"})


def test_without_old_sources_a_changed_conftest_is_not_read_as_changed(tmp_path: Path) -> None:
    """analyze_conftests only diffs what the caller hands it."""
    write_tree(tmp_path, {**BASE, "tests/conftest.py": CONFTEST})
    infos = scan_repo(tmp_path)
    verdict = analyze_conftests(tmp_path, ["tests/conftest.py"], set(), infos)
    assert verdict.block is None
    assert verdict.tainted == frozenset()
