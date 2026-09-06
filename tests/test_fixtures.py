"""Unit tests for the cross-file fixture graph.

Every case here is about one question: given a conftest chain and a set of
affected modules, which fixture names does the change reach, and when must
narrowing be refused for the whole subtree instead.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.fixtures import FileRequest, analyze_conftests, conftests_for, file_requests
from testsniper.scanner import scan_repo

BASE: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/changed.py": "def build() -> int:\n    return 1\n",
    "pkg/quiet.py": "def quiet() -> int:\n    return 2\n",
}

AFFECTED = {"pkg.changed"}


def _verdict(root: Path, files: dict[str, str], chain: list[str] | None = None):
    write_tree(root, {**BASE, **files})
    infos = scan_repo(root)
    return analyze_conftests(root, chain or ["tests/conftest.py"], AFFECTED, infos)


def test_only_the_fixture_that_reaches_the_change_is_tainted(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "from pkg.quiet import quiet\n"
                "\n"
                "@pytest.fixture\n"
                "def hot():\n"
                "    return build()\n"
                "\n"
                "@pytest.fixture\n"
                "def cold():\n"
                "    return quiet()\n"
            )
        },
    )
    assert verdict.block is None
    assert verdict.tainted == frozenset({"hot"})


def test_taint_propagates_through_another_fixture(tmp_path: Path) -> None:
    """A fixture that requests a tainted one is tainted too."""
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture\n"
                "def base():\n"
                "    return build()\n"
                "\n"
                "@pytest.fixture\n"
                "def wrapper(base):\n"
                "    return base * 2\n"
                "\n"
                "@pytest.fixture\n"
                "def unrelated():\n"
                "    return 0\n"
            )
        },
    )
    assert verdict.tainted == frozenset({"base", "wrapper"})


def test_taint_propagates_through_a_plain_helper(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "def _make():\n"
                "    return build()\n"
                "\n"
                "@pytest.fixture\n"
                "def thing():\n"
                "    return _make()\n"
            )
        },
    )
    assert verdict.tainted == frozenset({"thing"})


def test_a_local_import_inside_a_fixture_taints_it(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "@pytest.fixture\n"
                "def late():\n"
                "    from pkg.changed import build\n"
                "\n"
                "    return build()\n"
                "\n"
                "@pytest.fixture\n"
                "def early():\n"
                "    return 1\n"
            )
        },
    )
    assert verdict.tainted == frozenset({"late"})


def test_a_nearer_conftest_overrides_an_outer_fixture(tmp_path: Path) -> None:
    """pytest resolves nearest first, so a clean override is clean."""
    verdict = _verdict(
        tmp_path,
        {
            "conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture\n"
                "def db():\n"
                "    return build()\n"
            ),
            "tests/conftest.py": ("import pytest\n\n@pytest.fixture\ndef db():\n    return 0\n"),
        },
        chain=["conftest.py", "tests/conftest.py"],
    )
    assert verdict.tainted == frozenset()


def test_an_override_requesting_its_own_name_keeps_the_taint(tmp_path: Path) -> None:
    """``def db(db)`` asks for the definition it overrides, one level out."""
    verdict = _verdict(
        tmp_path,
        {
            "conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture\n"
                "def db():\n"
                "    return build()\n"
            ),
            "tests/conftest.py": (
                "import pytest\n\n@pytest.fixture\ndef db(db):\n    return db + 1\n"
            ),
        },
        chain=["conftest.py", "tests/conftest.py"],
    )
    assert verdict.tainted == frozenset({"db"})


def test_an_outer_fixture_is_visible_to_an_inner_directory(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture\n"
                "def shared():\n"
                "    return build()\n"
            ),
            "tests/conftest.py": (
                "import pytest\n\n@pytest.fixture\ndef local(shared):\n    return shared\n"
            ),
        },
        chain=["conftest.py", "tests/conftest.py"],
    )
    assert verdict.tainted == frozenset({"shared", "local"})


def test_the_renamed_fixture_name_is_what_gets_tainted(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                '@pytest.fixture(name="cart")\n'
                "def _cart():\n"
                "    return build()\n"
            )
        },
    )
    assert verdict.tainted == frozenset({"cart"})


def test_a_bare_fixture_decorator_is_recognized(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "from pytest import fixture\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@fixture\n"
                "def hot():\n"
                "    return build()\n"
            )
        },
    )
    assert verdict.tainted == frozenset({"hot"})


def test_mutually_recursive_fixtures_terminate(tmp_path: Path) -> None:
    """Not legal pytest, but it must not hang the analysis."""
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "@pytest.fixture\n"
                "def a(b):\n"
                "    return b\n"
                "\n"
                "@pytest.fixture\n"
                "def b(a):\n"
                "    return a\n"
            )
        },
    )
    assert verdict.block is None
    assert verdict.tainted == frozenset()


def test_an_unaffected_conftest_taints_nothing(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.quiet import quiet\n"
                "\n"
                "@pytest.fixture\n"
                "def cold():\n"
                "    return quiet()\n"
            )
        },
    )
    assert verdict.block is None
    assert verdict.tainted == frozenset()


def test_a_tainted_autouse_fixture_blocks_the_subtree(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture(autouse=True)\n"
                "def _setup():\n"
                "    build()\n"
            )
        },
    )
    assert verdict.block == "autouse fixture _setup in tests/conftest.py reaches the change"


def test_an_untainted_autouse_fixture_does_not_block(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "from pkg.quiet import quiet\n"
                "\n"
                "@pytest.fixture(autouse=True)\n"
                "def _setup():\n"
                "    quiet()\n"
                "\n"
                "@pytest.fixture\n"
                "def hot():\n"
                "    return build()\n"
            )
        },
    )
    assert verdict.block is None
    assert verdict.tainted == frozenset({"hot"})


def test_autouse_false_is_not_autouse(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture(autouse=False)\n"
                "def hot():\n"
                "    return build()\n"
            )
        },
    )
    assert verdict.block is None
    assert verdict.tainted == frozenset({"hot"})


def test_an_unreadable_autouse_value_counts_as_autouse(tmp_path: Path) -> None:
    """A computed autouse flag is read the safe way, not the convenient one."""
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import os\n"
                "\n"
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                'ALWAYS = bool(os.environ.get("CI"))\n'
                "\n"
                "@pytest.fixture(autouse=ALWAYS)\n"
                "def hot():\n"
                "    return build()\n"
            )
        },
    )
    assert verdict.block == "autouse fixture hot in tests/conftest.py reaches the change"


def test_a_tainted_hook_blocks_the_subtree(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "from pkg.changed import build\n"
                "\n"
                "def pytest_collection_modifyitems(items):\n"
                "    build()\n"
            )
        },
    )
    assert verdict.block == (
        "hook pytest_collection_modifyitems in tests/conftest.py uses an affected import"
    )


def test_an_untainted_hook_does_not_block(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "from pkg.quiet import quiet\n"
                "\n"
                "def pytest_report_header(config):\n"
                "    return str(quiet())\n"
                "\n"
                "@pytest.fixture\n"
                "def hot():\n"
                "    return build()\n"
            )
        },
    )
    assert verdict.block is None
    assert verdict.tainted == frozenset({"hot"})


def test_module_level_code_in_a_conftest_blocks(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {"tests/conftest.py": "from pkg.changed import build\n\nVALUE = build()\n"},
    )
    assert verdict.block == "module-level code in tests/conftest.py uses an affected import"


def test_pytest_plugins_blocks(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {"tests/conftest.py": 'from pkg.changed import build\n\npytest_plugins = ["other"]\n'},
    )
    assert verdict.block == (
        "tests/conftest.py sets pytest_plugins, which can add fixtures from anywhere"
    )


def test_a_star_import_of_the_change_blocks(tmp_path: Path) -> None:
    verdict = _verdict(tmp_path, {"tests/conftest.py": "from pkg.changed import *\n"})
    assert verdict.block is not None
    assert "star import" in verdict.block
    assert "tests/conftest.py" in verdict.block


def test_a_dynamic_import_blocks(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import importlib\n\nmod = importlib.import_module('pkg.changed')\n"
            )
        },
    )
    assert verdict.block == "tests/conftest.py imports dynamically"


def test_getfixturevalue_in_a_conftest_blocks(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture\n"
                "def indirect(request):\n"
                '    return request.getfixturevalue("build")\n'
            )
        },
    )
    assert verdict.block == "tests/conftest.py reads names dynamically (request.getfixturevalue)"


def test_an_unparseable_conftest_blocks(tmp_path: Path) -> None:
    verdict = _verdict(tmp_path, {"tests/conftest.py": "def broken(:\n"})
    assert verdict.block == "tests/conftest.py could not be parsed"


def test_an_outer_conftest_blocking_stops_the_whole_chain(tmp_path: Path) -> None:
    verdict = _verdict(
        tmp_path,
        {
            "conftest.py": "from pkg.changed import build\n\nVALUE = build()\n",
            "tests/conftest.py": "import pytest\n\n@pytest.fixture\ndef x():\n    return 1\n",
        },
        chain=["conftest.py", "tests/conftest.py"],
    )
    assert verdict.block == "module-level code in conftest.py uses an affected import"


# The other half of the module: which test files ask for those fixture names.
# Selection uses this to find the files an import graph cannot see.

NAMES = frozenset({"hot", "warm"})


def _requests(root: Path, source: str, names: frozenset[str] = NAMES) -> FileRequest:
    write_tree(root, {**BASE, "tests/test_it.py": source})
    return file_requests(root, "tests/test_it.py", "tests.test_it", names)


def test_a_parameter_requests_the_fixture(tmp_path: Path) -> None:
    request = _requests(tmp_path, "def test_a(hot) -> None:\n    assert hot\n")
    assert request.requested == frozenset({"hot"})
    assert request.unreadable is None


def test_a_name_the_file_never_reads_is_not_requested(tmp_path: Path) -> None:
    request = _requests(tmp_path, "def test_a(other) -> None:\n    assert other\n")
    assert request.requested == frozenset()


def test_a_fixture_in_the_file_passes_the_request_on(tmp_path: Path) -> None:
    request = _requests(
        tmp_path,
        "import pytest\n"
        "\n"
        "@pytest.fixture\n"
        "def wrapper(warm):\n"
        "    return warm\n"
        "\n"
        "def test_a(wrapper) -> None:\n"
        "    assert wrapper\n",
    )
    assert request.requested == frozenset({"warm"})


def test_a_method_on_a_class_requests_it_too(tmp_path: Path) -> None:
    request = _requests(
        tmp_path,
        "class TestThings:\n    def test_a(self, hot) -> None:\n        assert hot\n",
    )
    assert request.requested == frozenset({"hot"})


def test_an_unparseable_file_requests_everything(tmp_path: Path) -> None:
    request = _requests(tmp_path, "def test_a(:\n")
    assert request.requested == NAMES
    assert request.unreadable == "tests/test_it.py could not be parsed"


def test_getfixturevalue_makes_the_file_unreadable(tmp_path: Path) -> None:
    request = _requests(
        tmp_path,
        'def test_a(request) -> None:\n    assert request.getfixturevalue("hot")\n',
    )
    assert request.requested == NAMES
    assert request.unreadable is not None
    assert "request.getfixturevalue" in request.unreadable


def test_an_empty_name_set_reads_nothing(tmp_path: Path) -> None:
    """No affected fixture means no reason to open the file at all."""
    request = _requests(tmp_path, "def test_a(:\n", names=frozenset())
    assert request.requested == frozenset()
    assert request.unreadable is None


def test_conftests_for_lists_the_chain_outermost_first() -> None:
    assert conftests_for("tests/unit/test_it.py") == [
        "conftest.py",
        "tests/conftest.py",
        "tests/unit/conftest.py",
    ]
    assert conftests_for("test_it.py") == ["conftest.py"]
