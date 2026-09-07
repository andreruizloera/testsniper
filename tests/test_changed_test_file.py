"""Unit tests for reading a CHANGED test file through its own diff.

The other node tests ask which tests in a file reach a change somewhere else.
These ask the other question: the test file itself is what changed, so its
previous content decides which of its own tests moved.

Every case goes through ``narrow_file`` with ``is_changed=True``, the same
entry point ``narrow_selection`` uses, rather than through the private differ.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.config import load_config
from testsniper.nodes import narrow_file, narrow_selection
from testsniper.scanner import scan_repo
from testsniper.selector import select

BASE: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/one.py": "def one() -> int:\n    return 1\n",
}

TEST_FILE = (
    "import pytest\n"
    "\n"
    "from pkg.one import one\n"
    "\n"
    "\n"
    "def _double(n: int) -> int:\n"
    "    return n * 2\n"
    "\n"
    "\n"
    "@pytest.fixture\n"
    "def cart():\n"
    "    return [1, 2]\n"
    "\n"
    "\n"
    "def test_alpha():\n"
    "    assert one() == 1\n"
    "\n"
    "\n"
    "def test_beta():\n"
    "    assert _double(2) == 4\n"
    "\n"
    "\n"
    "def test_gamma(cart):\n"
    "    assert len(cart) == 2\n"
    "\n"
    "\n"
    "class TestGroup:\n"
    "    def test_in_class(self):\n"
    "        assert True\n"
    "\n"
    "    def test_other_in_class(self):\n"
    "        assert True\n"
)


def _narrow(root: Path, new: str, old: str | None, affected: set[str] | None = None):
    """Narrow tests/test_sample.py at content ``new``, diffed against ``old``."""
    write_tree(root, {**BASE, "tests/test_sample.py": new})
    return narrow_file(
        root,
        "tests/test_sample.py",
        affected or set(),
        "tests.test_sample",
        old_source=old,
        is_changed=True,
    )


def selected(nodes) -> set[str]:
    return {f"{cls}::{name}" if cls else name for cls, name in nodes.selected}


class TestWhatTheDiffSelects:
    def test_only_the_test_whose_body_moved(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("    assert one() == 1\n", "    assert one() == 1 + 0\n")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert nodes.narrowed
        assert nodes.reason == "narrowed by its own diff and name usage"
        assert selected(nodes) == {"test_alpha"}
        assert nodes.dropped == 4

    def test_an_added_test(self, tmp_path: Path) -> None:
        new = TEST_FILE + "\n\ndef test_new():\n    assert True\n"
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == {"test_new"}

    def test_a_changed_helper_selects_the_tests_that_call_it(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("    return n * 2\n", "    return n + n\n")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == {"test_beta"}

    def test_a_changed_fixture_selects_the_tests_that_request_it(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("    return [1, 2]\n", "    return [1, 1]\n")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == {"test_gamma"}

    def test_a_deleted_fixture_selects_the_tests_that_still_ask_for_it(
        self, tmp_path: Path
    ) -> None:
        """No node is left to walk to, so the name itself carries the change."""
        new = TEST_FILE.replace("@pytest.fixture\ndef cart():\n    return [1, 2]\n\n\n", "")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == {"test_gamma"}

    def test_a_changed_import_selects_the_tests_that_read_the_name(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace(
            "from pkg.one import one\n", "from pkg.one import one as one  # noqa: PLC0414\n"
        )
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == {"test_alpha"}

    def test_a_deleted_test_selects_nothing(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("def test_alpha():\n    assert one() == 1\n\n\n", "")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == set()

    def test_a_comment_only_edit_selects_nothing(self, tmp_path: Path) -> None:
        """Parsed syntax, not text: a comment is not a change to anything."""
        new = TEST_FILE.replace("    assert one() == 1\n", "    assert one() == 1  # sanity\n")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert nodes.narrowed
        assert selected(nodes) == set()

    def test_the_diff_unions_with_an_affected_import(self, tmp_path: Path) -> None:
        """The file changed AND imports the change; both channels apply."""
        new = TEST_FILE.replace("    return n * 2\n", "    return n + n\n")
        nodes = _narrow(tmp_path, new, TEST_FILE, affected={"pkg.one"})
        assert selected(nodes) == {"test_alpha", "test_beta"}


class TestClasses:
    def test_one_changed_method_does_not_select_its_siblings(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace(
            "    def test_in_class(self):\n        assert True\n",
            "    def test_in_class(self):\n        assert True is True\n",
        )
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == {"TestGroup::test_in_class"}

    def test_a_changed_class_body_selects_every_test_on_it(self, tmp_path: Path) -> None:
        """Class-body state is shared by every method, so all of them move."""
        new = TEST_FILE.replace("class TestGroup:\n", "class TestGroup:\n    limit = 3\n\n")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert selected(nodes) == {"TestGroup::test_in_class", "TestGroup::test_other_in_class"}

    def test_a_changed_helper_method_selects_the_method_that_calls_it(self, tmp_path: Path) -> None:
        with_helper = TEST_FILE.replace(
            "class TestGroup:\n",
            "class TestGroup:\n    def _limit(self):\n        return 3\n\n",
        ).replace(
            "    def test_in_class(self):\n        assert True\n",
            "    def test_in_class(self):\n        assert self._limit() == 3\n",
        )
        new = with_helper.replace("        return 3\n", "        return 1 + 2\n")
        nodes = _narrow(tmp_path, new, with_helper)
        assert selected(nodes) == {"TestGroup::test_in_class"}


class TestRefusals:
    def test_a_brand_new_file_runs_whole(self, tmp_path: Path) -> None:
        nodes = _narrow(tmp_path, TEST_FILE, None)
        assert not nodes.narrowed
        assert nodes.reason == ("this file is new; there is no previous content to compare against")

    def test_unparseable_previous_content_runs_whole(self, tmp_path: Path) -> None:
        nodes = _narrow(tmp_path, TEST_FILE, "def broken(:\n")
        assert not nodes.narrowed
        assert nodes.reason == "the previous content of this file could not be parsed"

    def test_changed_module_level_code_runs_whole(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("import pytest\n", "import pytest\n\nLIMIT = 5\n")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert not nodes.narrowed
        assert nodes.reason == "module-level code in this file changed; it runs on import"

    def test_module_level_code_reading_a_changed_name_runs_whole(self, tmp_path: Path) -> None:
        """The statement did not move, but what it reads did."""
        base = TEST_FILE.replace(
            "def test_alpha():\n",
            "pytestmark = pytest.mark.skipif(_double(0) > 0, reason='x')\n\n\ndef test_alpha():\n",
        )
        new = base.replace("    return n * 2\n", "    return n + n\n")
        nodes = _narrow(tmp_path, new, base)
        assert not nodes.narrowed
        assert nodes.reason == "module-level code in this file reads something the diff changed"

    def test_a_changed_autouse_fixture_runs_whole(self, tmp_path: Path) -> None:
        base = TEST_FILE.replace(
            "@pytest.fixture\ndef cart():",
            "@pytest.fixture(autouse=True)\n"
            "def _setup():\n"
            "    return 0\n"
            "\n"
            "\n"
            "@pytest.fixture\n"
            "def cart():",
        )
        new = base.replace("def _setup():\n    return 0\n", "def _setup():\n    return 1\n")
        nodes = _narrow(tmp_path, new, base)
        assert not nodes.narrowed
        assert nodes.reason == "autouse fixture _setup in this file changed"

    def test_a_removed_autouse_fixture_runs_whole(self, tmp_path: Path) -> None:
        base = TEST_FILE.replace(
            "@pytest.fixture\ndef cart():",
            "@pytest.fixture(autouse=True)\n"
            "def _setup():\n"
            "    return 0\n"
            "\n"
            "\n"
            "@pytest.fixture\n"
            "def cart():",
        )
        nodes = _narrow(tmp_path, TEST_FILE, base)
        assert not nodes.narrowed
        assert nodes.reason == "autouse fixture _setup was removed from this file"

    def test_a_changed_hook_runs_whole(self, tmp_path: Path) -> None:
        """pytest_generate_tests in a test module parametrizes every test in it."""
        base = TEST_FILE + "\n\ndef pytest_generate_tests(metafunc):\n    return None\n"
        new = base.replace(
            "def pytest_generate_tests(metafunc):\n    return None\n",
            "def pytest_generate_tests(metafunc):\n    return\n",
        )
        nodes = _narrow(tmp_path, new, base)
        assert not nodes.narrowed
        assert nodes.reason == (
            "hook pytest_generate_tests in this file changed; hooks see every collected item"
        )

    def test_a_removed_hook_runs_whole(self, tmp_path: Path) -> None:
        base = TEST_FILE + "\n\ndef pytest_generate_tests(metafunc):\n    return None\n"
        nodes = _narrow(tmp_path, TEST_FILE, base)
        assert not nodes.narrowed
        assert nodes.reason == "hook pytest_generate_tests was removed from this file"

    def test_a_changed_star_import_runs_whole(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("from pkg.one import one\n", "from pkg.one import *\n")
        nodes = _narrow(tmp_path, new, TEST_FILE)
        assert not nodes.narrowed
        assert nodes.reason == "a star import in this file changed"

    def test_previous_content_with_a_dynamic_import_runs_whole(self, tmp_path: Path) -> None:
        base = TEST_FILE.replace(
            "def test_alpha():\n    assert one() == 1\n",
            "def test_alpha():\n    import importlib\n\n    importlib.import_module('pkg.one')\n",
        )
        nodes = _narrow(tmp_path, TEST_FILE, base)
        assert not nodes.narrowed
        assert nodes.reason == "the previous content of this file imports dynamically"


PROJECT: dict[str, str] = {
    **BASE,
    "pyproject.toml": (
        "[project]\n"
        'name = "sample"\n'
        'version = "0.1.0"\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
    ),
}


def _selection_nodes(root: Path, new: str, old: str | None, mode: str = "default"):
    """Go the whole way: select the changed test file, then narrow it."""
    write_tree(root, {**PROJECT, "tests/test_sample.py": new})
    infos = scan_repo(root)
    selection = select(
        root,
        ["tests/test_sample.py"],
        mode,  # type: ignore[arg-type]
        load_config(root),
        infos,
        old_source=lambda rel: old if rel == "tests/test_sample.py" else None,
    )
    return selection, narrow_selection(root, selection, infos)


class TestThroughSelection:
    def test_the_file_is_still_selected_and_now_narrowed(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("    assert one() == 1\n", "    assert one() == 1 + 0\n")
        selection, nodes = _selection_nodes(tmp_path, new, TEST_FILE)
        picked = next(t for t in selection.tests if t.relpath == "tests/test_sample.py")
        assert picked.reason == "changed test file"
        assert selected(nodes["tests/test_sample.py"]) == {"test_alpha"}

    def test_safe_mode_runs_the_whole_file(self, tmp_path: Path) -> None:
        new = TEST_FILE.replace("    assert one() == 1\n", "    assert one() == 1 + 0\n")
        _, nodes = _selection_nodes(tmp_path, new, TEST_FILE, mode="safe")
        assert nodes["tests/test_sample.py"].reason == "the test file itself changed"

    def test_a_caller_with_no_previous_content_runs_the_whole_file(self, tmp_path: Path) -> None:
        """Selection records nothing to diff against, so the older answer stands."""
        new = TEST_FILE.replace("    assert one() == 1\n", "    assert one() == 1 + 0\n")
        write_tree(tmp_path, {**PROJECT, "tests/test_sample.py": new})
        infos = scan_repo(tmp_path)
        selection = select(
            tmp_path, ["tests/test_sample.py"], "default", load_config(tmp_path), infos
        )
        nodes = narrow_selection(tmp_path, selection, infos)
        assert nodes["tests/test_sample.py"].reason == "the test file itself changed"
