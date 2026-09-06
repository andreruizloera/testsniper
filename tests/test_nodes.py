"""Tests for node-level narrowing: which test functions reach the change.

Every case is written against one small test file whose content is the
subject. The affected set is passed directly so these stay unit tests of the
name-usage analysis, not of git or of the import graph.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.config import load_config
from testsniper.nodes import (
    FileNodes,
    conftests_for,
    is_affected,
    narrow_file,
    narrow_selection,
)
from testsniper.scanner import scan_repo
from testsniper.selector import select


def _narrow(
    tmp_path: Path,
    source: str,
    affected: set[str] | None = None,
    relpath: str = "tests/test_it.py",
    module: str = "test_it",
) -> FileNodes:
    write_tree(tmp_path, {relpath: source})
    return narrow_file(tmp_path, relpath, affected or {"pkg.changed"}, module)


def _names(nodes: FileNodes) -> set[str]:
    return {name for _cls, name in nodes.selected}


def test_direct_import_selects_only_its_users(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import touched\n"
        "from pkg.other import untouched\n"
        "\n"
        "def test_a():\n"
        "    assert touched()\n"
        "\n"
        "def test_b():\n"
        "    assert untouched()\n",
    )
    assert nodes.narrowed
    assert _names(nodes) == {"test_a"}
    assert nodes.known == {("", "test_a"), ("", "test_b")}
    assert nodes.dropped == 1


def test_alias_import_is_followed(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "import pkg.changed as c\n"
        "import pkg.other as o\n"
        "\n"
        "def test_a():\n"
        "    assert c.value()\n"
        "\n"
        "def test_b():\n"
        "    assert o.value()\n",
    )
    assert _names(nodes) == {"test_a"}


def test_plain_dotted_import_binds_the_root_package(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "import pkg.changed\nimport json\n"
        "\n"
        "def test_a():\n"
        "    assert pkg.changed.value()\n"
        "\n"
        "def test_b():\n"
        "    assert json.dumps({})\n",
    )
    assert _names(nodes) == {"test_a"}


def test_importing_a_package_above_an_affected_module(tmp_path: Path) -> None:
    """``from pkg import changed`` reaches ``pkg.changed`` as a submodule."""
    nodes = _narrow(
        tmp_path,
        "from pkg import changed, other\n"
        "\n"
        "def test_a():\n"
        "    assert changed.value()\n"
        "\n"
        "def test_b():\n"
        "    assert other.value()\n",
    )
    assert _names(nodes) == {"test_a"}


def test_unrelated_sibling_package_is_not_affected(tmp_path: Path) -> None:
    """``pkg.changed_other`` must not match on the ``pkg.changed`` prefix."""
    nodes = _narrow(
        tmp_path,
        "from pkg.changed_other import thing\n\ndef test_a():\n    assert thing()\n",
    )
    assert nodes.narrowed
    assert _names(nodes) == set()


def test_fixture_is_reached_through_the_parameter_that_requests_it(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "import pytest\n"
        "from pkg.changed import build\n"
        "\n"
        "@pytest.fixture\n"
        "def client():\n"
        "    return build()\n"
        "\n"
        "@pytest.fixture\n"
        "def plain():\n"
        "    return 1\n"
        "\n"
        "def test_a(client):\n"
        "    assert client\n"
        "\n"
        "def test_b(plain):\n"
        "    assert plain\n",
    )
    assert _names(nodes) == {"test_a"}


def test_usage_propagates_through_a_chain_of_helpers(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "def _inner():\n"
        "    return build()\n"
        "\n"
        "def _outer():\n"
        "    return _inner()\n"
        "\n"
        "def test_a():\n"
        "    assert _outer()\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert _names(nodes) == {"test_a"}


def test_mutually_recursive_helpers_terminate(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "def ping(n):\n"
        "    return pong(n) if n else build()\n"
        "\n"
        "def pong(n):\n"
        "    return ping(n - 1)\n"
        "\n"
        "def test_a():\n"
        "    assert ping(3)\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert _names(nodes) == {"test_a"}


def test_class_methods_carry_a_class_path(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "class TestOne:\n"
        "    def test_a(self):\n"
        "        assert build()\n"
        "\n"
        "    def test_b(self):\n"
        "        assert True\n",
    )
    assert nodes.selected == {("TestOne", "test_a")}
    assert nodes.known == {("TestOne", "test_a"), ("TestOne", "test_b")}


def test_sibling_method_call_propagates_within_a_class(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "class TestOne:\n"
        "    def _make(self):\n"
        "        return build()\n"
        "\n"
        "    def test_a(self):\n"
        "        assert self._make()\n"
        "\n"
        "    def test_b(self):\n"
        "        assert True\n",
    )
    assert nodes.selected == {("TestOne", "test_a")}


def test_same_method_name_in_two_classes_does_not_leak(tmp_path: Path) -> None:
    """``self._make`` must resolve inside its own class, not the other one."""
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "class TestOne:\n"
        "    def _make(self):\n"
        "        return build()\n"
        "\n"
        "    def test_a(self):\n"
        "        assert self._make()\n"
        "\n"
        "class TestTwo:\n"
        "    def _make(self):\n"
        "        return 1\n"
        "\n"
        "    def test_b(self):\n"
        "        assert self._make()\n",
    )
    assert nodes.selected == {("TestOne", "test_a")}


def test_nested_class_key_joins_both_class_names(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "class TestOuter:\n"
        "    class TestInner:\n"
        "        def test_a(self):\n"
        "            assert build()\n"
        "\n"
        "        def test_b(self):\n"
        "            assert True\n",
    )
    assert nodes.selected == {("TestOuter::TestInner", "test_a")}


def test_class_body_state_selects_every_method_on_it(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "class TestOne:\n"
        "    VALUE = build()\n"
        "\n"
        "    def test_a(self):\n"
        "        assert True\n"
        "\n"
        "    def test_b(self):\n"
        "        assert True\n",
    )
    assert nodes.selected == {("TestOne", "test_a"), ("TestOne", "test_b")}


def test_decorator_argument_counts_as_usage(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "import pytest\n"
        "from pkg.changed import CASES\n"
        "\n"
        "@pytest.mark.parametrize('n', CASES)\n"
        "def test_a(n):\n"
        "    assert n\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert _names(nodes) == {"test_a"}


def test_function_local_import_selects_only_that_function(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "def test_a():\n"
        "    from pkg.changed import build\n"
        "    assert build()\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert nodes.narrowed
    assert _names(nodes) == {"test_a"}


def test_module_level_code_using_the_change_stops_narrowing(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n\nCLIENT = build()\n\ndef test_a():\n    assert True\n",
    )
    assert not nodes.narrowed
    assert nodes.reason == "module-level code uses an affected import"
    assert nodes.keeps(("", "test_a"))
    assert nodes.dropped == 0


def test_module_level_code_not_touching_the_change_still_narrows(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "CASES = [1, 2, 3]\n"
        "\n"
        "def test_a():\n"
        "    assert build()\n"
        "\n"
        "def test_b():\n"
        "    assert CASES\n",
    )
    assert nodes.narrowed
    assert _names(nodes) == {"test_a"}


def test_star_import_of_the_change_stops_narrowing(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import *\n\ndef test_a():\n    assert True\n",
    )
    assert not nodes.narrowed
    assert "star import" in nodes.reason


def test_star_import_of_something_else_does_not_stop_narrowing(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.other import *\n"
        "from pkg.changed import build\n"
        "\n"
        "def test_a():\n"
        "    assert build()\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert nodes.narrowed
    assert _names(nodes) == {"test_a"}


def test_dynamic_import_stops_narrowing(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "import importlib\n"
        "\n"
        "def test_a():\n"
        "    assert importlib.import_module('pkg.changed')\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert not nodes.narrowed
    assert nodes.reason == "the file imports dynamically"


def test_globals_lookup_stops_narrowing(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "def test_a():\n"
        "    assert globals()['build']()\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert not nodes.narrowed
    assert "dynamically" in nodes.reason


def test_unresolved_relative_import_stops_narrowing(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from ... import helper\n\ndef test_a():\n    assert helper()\n",
    )
    assert not nodes.narrowed
    assert "relative import" in nodes.reason


def test_unparsable_file_stops_narrowing(tmp_path: Path) -> None:
    nodes = _narrow(tmp_path, "def test_a(:\n    pass\n")
    assert not nodes.narrowed
    assert nodes.reason == "the file could not be parsed"


def test_file_with_no_test_functions_is_not_narrowed(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path, "from pkg.changed import build\n\ndef helper():\n    return build()\n"
    )
    assert not nodes.narrowed
    assert "no test functions" in nodes.reason


def test_nothing_selected_is_a_valid_narrowing(tmp_path: Path) -> None:
    """A file can import the change and have no test that touches it."""
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "def unused_helper():\n"
        "    return build()\n"
        "\n"
        "def test_a():\n"
        "    assert True\n",
    )
    assert nodes.narrowed
    assert nodes.selected == set()
    assert nodes.dropped == 1


def test_keeps_unknown_items_even_when_narrowed(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from pkg.changed import build\n"
        "\n"
        "def test_a():\n"
        "    assert build()\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
    )
    assert nodes.keeps(("", "test_a"))
    assert not nodes.keeps(("", "test_b"))
    # A doctest or an item from a custom collector was never analyzed.
    assert nodes.keeps(("", "some_doctest"))


def test_relative_import_inside_a_package_resolves(tmp_path: Path) -> None:
    nodes = _narrow(
        tmp_path,
        "from .changed import build\n"
        "from .other import quiet\n"
        "\n"
        "def test_a():\n"
        "    assert build()\n"
        "\n"
        "def test_b():\n"
        "    assert quiet()\n",
        relpath="pkg/tests/test_it.py",
        module="pkg.tests.test_it",
        affected={"pkg.tests.changed"},
    )
    assert _names(nodes) == {"test_a"}


def test_is_affected_prefix_and_submodule_rules() -> None:
    affected = {"pkg.changed"}
    assert is_affected("pkg.changed", affected)
    assert is_affected("pkg.changed.deep", affected) is False
    assert is_affected("pkg", affected)  # an affected submodule sits under it
    assert is_affected("pkg.changed_other", affected) is False
    assert is_affected("other", affected) is False
    # A plain "import a.b.c" also executes a and a.b.
    assert is_affected("pkg.changed.deep", {"pkg"}, with_prefixes=True)
    assert is_affected("pkg.changed.deep", {"pkg"}) is False


def _selection_nodes(root: Path, changed: list[str], mode: str = "default"):
    infos = scan_repo(root)
    sel = select(root, changed, mode, load_config(root), infos)  # type: ignore[arg-type]
    return sel, narrow_selection(root, sel, infos)


def test_always_run_files_keep_every_test(sample_project: Path) -> None:
    _sel, nodes = _selection_nodes(sample_project, ["pkg/core.py"])
    smoke = nodes["tests/smoke/test_smoke.py"]
    assert not smoke.narrowed
    assert smoke.reason == "always_run (tests/smoke)"
    assert nodes["tests/test_core.py"].narrowed


def test_a_changed_test_file_keeps_every_test(sample_project: Path) -> None:
    _sel, nodes = _selection_nodes(sample_project, ["tests/test_core.py"])
    assert nodes["tests/test_core.py"].reason == "the test file itself changed"
    assert not nodes["tests/test_core.py"].narrowed


def test_safe_mode_select_all_keeps_every_test(sample_project: Path) -> None:
    """A non-Python change in safe mode selects everything; nothing narrows."""
    _sel, nodes = _selection_nodes(sample_project, ["README.md"], mode="safe")
    assert nodes
    assert all(not n.narrowed and n.reason == "everything is selected" for n in nodes.values())


def test_transitive_importers_narrow_on_the_module_they_import(sample_project: Path) -> None:
    """test_top.py imports pkg.top, which is what makes it affected at distance 3."""
    _sel, nodes = _selection_nodes(sample_project, ["pkg/core.py"])
    top = nodes["tests/test_top.py"]
    assert top.narrowed
    assert {name for _cls, name in top.selected} == {"test_top"}


def test_an_affected_conftest_stops_narrowing_in_its_subtree(sample_project: Path) -> None:
    write_tree(
        sample_project,
        {"tests/conftest.py": "from pkg.core import core\n\nRATE = core()\n"},
    )
    _sel, nodes = _selection_nodes(sample_project, ["pkg/core.py"])
    entry = nodes["tests/test_core.py"]
    assert not entry.narrowed
    assert entry.reason == "tests/conftest.py is affected and its fixtures apply here"


def test_conftests_for_lists_every_applicable_directory() -> None:
    assert conftests_for("tests/unit/test_it.py") == [
        "conftest.py",
        "tests/conftest.py",
        "tests/unit/conftest.py",
    ]
    assert conftests_for("test_it.py") == ["conftest.py"]
