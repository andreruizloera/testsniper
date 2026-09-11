"""File-level selection through a conftest fixture.

The import graph cannot see these files at all. A test file that imports
nothing affected is not in the change's closure, so node narrowing never sees
it either: narrowing only ever removes tests from an already-selected file.
What connects it to the change is a fixture name resolved in a conftest.py the
file never mentions.

Every case here is about which files that channel selects, and what it costs
when the conftest does something that applies to every test underneath it.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.config import load_config
from testsniper.fixtures import FixtureVerdict
from testsniper.nodes import narrow_selection
from testsniper.scanner import scan_repo
from testsniper.selector import Selection, select

PROJECT: dict[str, str] = {
    "pyproject.toml": (
        "[project]\n"
        'name = "sample"\n'
        'version = "0.1.0"\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
    ),
    "pkg/__init__.py": "",
    "pkg/changed.py": "def build() -> int:\n    return 1\n",
    "pkg/quiet.py": "def quiet() -> int:\n    return 2\n",
    # Mixed on purpose: one fixture the change reaches, one it does not.
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
    ),
    # Imports nothing at all. The fixture is the only channel.
    "tests/test_asks.py": "def test_asks(hot) -> None:\n    assert hot == 1\n",
    "tests/test_quiet.py": "def test_quiet(cold) -> None:\n    assert cold == 2\n",
}


def _select(root: Path, files: dict[str, str] | None = None, mode: str = "default") -> Selection:
    write_tree(root, {**PROJECT, **(files or {})})
    return select(root, ["pkg/changed.py"], mode, load_config(root))  # type: ignore[arg-type]


def _paths(sel: Selection) -> list[str]:
    return [t.relpath for t in sel.tests]


def _picked(sel: Selection, relpath: str):
    return next(t for t in sel.tests if t.relpath == relpath)


def test_a_file_that_only_asks_for_the_fixture_is_selected(tmp_path: Path) -> None:
    sel = _select(tmp_path)
    assert "tests/test_asks.py" in _paths(sel)
    picked = _picked(sel, "tests/test_asks.py")
    assert picked.distance is None
    assert picked.via_fixture
    assert picked.channel == "fixture"
    assert picked.reason == "requests affected fixture hot from tests/conftest.py"


def test_a_file_that_asks_for_an_unaffected_fixture_is_not_selected(tmp_path: Path) -> None:
    """The point of the whole exercise: an affected conftest is not a subtree."""
    sel = _select(tmp_path)
    assert "tests/test_quiet.py" not in _paths(sel)


def test_the_note_names_the_conftest_and_the_fixture(tmp_path: Path) -> None:
    sel = _select(tmp_path)
    assert sel.notes == [
        "tests/conftest.py is affected through hot; selecting the tests that request those fixtures"
    ]


def test_a_usefixtures_mark_requests_the_fixture(tmp_path: Path) -> None:
    sel = _select(
        tmp_path,
        {
            "tests/test_asks.py": (
                "import pytest\n"
                "\n"
                '@pytest.mark.usefixtures("hot")\n'
                "def test_marked() -> None:\n"
                "    assert True\n"
            )
        },
    )
    assert "tests/test_asks.py" in _paths(sel)


def test_the_files_own_fixture_carries_the_request(tmp_path: Path) -> None:
    """A local fixture that requests the tainted one passes it on."""
    sel = _select(
        tmp_path,
        {
            "tests/test_asks.py": (
                "import pytest\n"
                "\n"
                "@pytest.fixture\n"
                "def wrapper(hot):\n"
                "    return hot + 1\n"
                "\n"
                "def test_wrapped(wrapper) -> None:\n"
                "    assert wrapper == 2\n"
            )
        },
    )
    assert "tests/test_asks.py" in _paths(sel)


def test_a_nearer_conftest_that_overrides_the_fixture_shields_its_files(tmp_path: Path) -> None:
    """pytest resolves the nearest definition, so this file never sees the change."""
    sel = _select(
        tmp_path,
        {
            "tests/inner/conftest.py": (
                "import pytest\n\n@pytest.fixture\ndef hot():\n    return 99\n"
            ),
            "tests/inner/test_inner.py": "def test_inner(hot) -> None:\n    assert hot == 99\n",
        },
    )
    assert "tests/inner/test_inner.py" not in _paths(sel)
    assert "tests/test_asks.py" in _paths(sel)


def test_an_autouse_fixture_selects_every_file_underneath(tmp_path: Path) -> None:
    """The under-selection this feature closes.

    An autouse fixture runs for tests that never name it, so a change it
    reaches reaches every test in the subtree, including files that import
    nothing and request nothing.
    """
    sel = _select(
        tmp_path,
        {
            "tests/conftest.py": (
                "import pytest\n"
                "\n"
                "from pkg.changed import build\n"
                "\n"
                "@pytest.fixture(autouse=True)\n"
                "def _prepare():\n"
                "    build()\n"
                "    yield\n"
            )
        },
    )
    assert sorted(_paths(sel)) == ["tests/test_asks.py", "tests/test_quiet.py"]
    picked = _picked(sel, "tests/test_quiet.py")
    assert picked.reason == "autouse fixture _prepare in tests/conftest.py reaches the change"
    assert not picked.narrowable
    assert sel.notes == [
        "autouse fixture _prepare in tests/conftest.py reaches the change,"
        " so every test it applies to is selected"
    ]


def test_a_conftest_hook_selects_every_file_underneath(tmp_path: Path) -> None:
    sel = _select(
        tmp_path,
        {
            "tests/conftest.py": (
                "from pkg.changed import build\n\ndef pytest_runtest_setup(item):\n    build()\n"
            )
        },
    )
    assert sorted(_paths(sel)) == ["tests/test_asks.py", "tests/test_quiet.py"]
    assert "hook pytest_runtest_setup" in _picked(sel, "tests/test_quiet.py").reason


def test_module_level_conftest_code_selects_every_file_underneath(tmp_path: Path) -> None:
    sel = _select(
        tmp_path,
        {"tests/conftest.py": "from pkg.changed import build\n\nREADY = build()\n"},
    )
    assert sorted(_paths(sel)) == ["tests/test_asks.py", "tests/test_quiet.py"]
    assert "module-level code" in _picked(sel, "tests/test_quiet.py").reason


def test_a_test_file_that_does_not_parse_is_selected(tmp_path: Path) -> None:
    """Unreadable means unknown, and unknown is selected, not dropped."""
    sel = _select(tmp_path, {"tests/test_quiet.py": "def test_broken(:\n    pass\n"})
    assert "tests/test_quiet.py" in _paths(sel)
    assert "could not be parsed" in _picked(sel, "tests/test_quiet.py").reason


def test_getfixturevalue_means_the_file_may_ask_for_anything(tmp_path: Path) -> None:
    sel = _select(
        tmp_path,
        {
            "tests/test_quiet.py": (
                "def test_dynamic(request) -> None:\n"
                '    assert request.getfixturevalue("cold") == 2\n'
            )
        },
    )
    picked = _picked(sel, "tests/test_quiet.py")
    assert "reads names dynamically (request.getfixturevalue)" in picked.reason


def test_safe_mode_takes_the_whole_subtree(tmp_path: Path) -> None:
    """Safe mode widens the change to the whole package, and says what that cost.

    Widening makes ``pkg`` itself part of the change set, and ``pkg`` is a
    package the conftest's own imports execute on the way to ``pkg.changed``.
    There is no name binding that stands for that side effect, so the conftest
    stops being narrowable at all. The file is selected whole either way; what
    the reason records is which decision made it unnarrowable, and under
    ``--safe`` that decision is safe mode's own widening.
    """
    sel = _select(tmp_path, mode="safe")
    assert "tests/test_quiet.py" in _paths(sel)
    assert _picked(sel, "tests/test_quiet.py").reason == (
        "tests/conftest.py imports from pkg.changed,"
        " and its package pkg is affected and runs on import"
    )


def test_aggressive_mode_ignores_the_fixture_and_says_so(tmp_path: Path) -> None:
    sel = _select(tmp_path, mode="aggressive")
    assert _paths(sel) == []
    assert sel.confidence == "Low"
    assert any(
        "affected conftest.py fixtures ignored in aggressive mode (tests/conftest.py)" in reason
        for reason in sel.confidence_reasons
    )


def test_a_module_reached_only_through_a_fixture_is_not_reported_unreached(
    tmp_path: Path,
) -> None:
    """No test imports pkg.changed, but a test does run because of it."""
    sel = _select(tmp_path)
    assert sel.unreached == []
    assert sel.confidence == "High"


def test_a_fixture_selected_file_is_still_narrowed(tmp_path: Path) -> None:
    """Selection finds the file; narrowing still decides which of its tests run."""
    write_tree(
        tmp_path,
        {
            **PROJECT,
            "tests/test_asks.py": (
                "def test_asks(hot) -> None:\n"
                "    assert hot == 1\n"
                "\n"
                "def test_alone() -> None:\n"
                "    assert True\n"
            ),
        },
    )
    infos = scan_repo(tmp_path)
    sel = select(tmp_path, ["pkg/changed.py"], "default", load_config(tmp_path), infos)
    nodes = narrow_selection(tmp_path, sel, infos)
    asks = nodes["tests/test_asks.py"]
    assert asks.narrowed
    assert asks.selected == {("", "test_asks")}
    assert asks.dropped == 1


def test_narrowing_reuses_the_verdict_selection_computed(tmp_path: Path) -> None:
    """One reading of the conftest chain, so the two answers cannot disagree."""
    write_tree(tmp_path, PROJECT)
    infos = scan_repo(tmp_path)
    sel = select(tmp_path, ["pkg/changed.py"], "default", load_config(tmp_path), infos)
    assert ("tests/conftest.py",) in sel.fixture_verdicts

    sel.fixture_verdicts[("tests/conftest.py",)] = FixtureVerdict(block="poisoned")
    nodes = narrow_selection(tmp_path, sel, infos)
    assert nodes["tests/test_asks.py"].reason == "poisoned"


def test_a_file_under_a_changed_conftest_is_never_narrowed(tmp_path: Path) -> None:
    """A changed conftest is not something per-test name usage can refine.

    The file below both imports the change and sits under the conftest that
    changed. Before this rule the import distance won and the file was
    narrowed as if the conftest were untouched, dropping the tests that use
    its fixtures.
    """
    write_tree(
        tmp_path,
        {
            **PROJECT,
            "tests/test_asks.py": (
                "from pkg.changed import build\n"
                "\n"
                "def test_direct() -> None:\n"
                "    assert build() == 1\n"
                "\n"
                "def test_through_a_fixture(cold) -> None:\n"
                "    assert cold == 2\n"
            ),
        },
    )
    infos = scan_repo(tmp_path)
    sel = select(
        tmp_path,
        ["pkg/changed.py", "tests/conftest.py"],
        "default",
        load_config(tmp_path),
        infos,
    )
    picked = _picked(sel, "tests/test_asks.py")
    assert picked.distance == 1
    assert not picked.narrowable
    nodes = narrow_selection(tmp_path, sel, infos)
    assert not nodes["tests/test_asks.py"].narrowed
    assert nodes["tests/test_asks.py"].reason == "under changed tests/conftest.py"
