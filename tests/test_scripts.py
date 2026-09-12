"""Reading console scripts out of packaging metadata.

The metadata is the only place that says what a program name means, so a
wrong reading here either invents an edge (a test runs for nothing) or loses
one (a test that runs the command line is never selected). Refusals are
tested as carefully as matches.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from conftest import write_tree

from testsniper.scanner import SKIP_DIRS, scan_repo
from testsniper.scripts import (
    entry_point_module,
    load_scripts,
    pyproject_scripts,
    setup_cfg_scripts,
)


def test_an_object_reference_imports_its_module() -> None:
    assert entry_point_module("pkg.cli:main") == "pkg.cli"


def test_a_nested_object_and_extras_still_name_the_module() -> None:
    assert entry_point_module("pkg.cli:Group.main") == "pkg.cli"
    assert entry_point_module(" pkg.cli : main [color, extra] ") == "pkg.cli"


def test_a_reference_with_no_object_is_the_module() -> None:
    assert entry_point_module("pkg.cli") == "pkg.cli"


def test_a_reference_that_is_not_a_dotted_name_is_refused() -> None:
    for bad in ["", ":main", "bin/tool.py", "pkg-cli:main", "pkg..cli:main"]:
        assert entry_point_module(bad) is None, bad


def test_project_scripts_and_gui_scripts_are_both_read() -> None:
    data = tomllib.loads(
        "[project]\n"
        'name = "x"\n'
        "[project.scripts]\n"
        'greet = "pkg.cli:main"\n'
        "[project.gui-scripts]\n"
        'window = "pkg.gui:run"\n'
    )
    assert pyproject_scripts(data) == {"greet": {"pkg.cli"}, "window": {"pkg.gui"}}


def test_poetry_strings_and_console_tables_are_read_and_file_scripts_are_not() -> None:
    """`tools` would be a valid module name, so only the type refuses it."""
    data = tomllib.loads(
        "[tool.poetry.scripts]\n"
        'greet = "pkg.cli:main"\n'
        'check = { reference = "pkg.checks:run", type = "console" }\n'
        'binary = { reference = "tools", type = "file" }\n'
    )
    assert pyproject_scripts(data) == {"greet": {"pkg.cli"}, "check": {"pkg.checks"}}


def test_a_pyproject_without_scripts_declares_nothing() -> None:
    assert pyproject_scripts(tomllib.loads('[project]\nname = "x"\n')) == {}


def test_a_scripts_table_of_the_wrong_shape_is_ignored_rather_than_fatal() -> None:
    data = tomllib.loads('[project]\nscripts = "not a table"\n[tool]\npoetry = 3\n')
    assert pyproject_scripts(data) == {}


def test_setup_cfg_console_and_gui_scripts_are_read_and_other_entry_points_are_not() -> None:
    text = (
        "[metadata]\n"
        "name = x\n"
        "description = 100% of the scripts\n"
        "\n"
        "[options.entry_points]\n"
        "console_scripts =\n"
        "    greet = pkg.cli:main\n"
        "    other = pkg.other:main [extra]\n"
        "gui_scripts =\n"
        "    window = pkg.gui:run\n"
        "pytest11 =\n"
        "    plug = pkg.plugin\n"
    )
    assert setup_cfg_scripts(text) == {
        "greet": {"pkg.cli"},
        "other": {"pkg.other"},
        "window": {"pkg.gui"},
    }


def test_an_unparseable_setup_cfg_declares_nothing() -> None:
    assert setup_cfg_scripts("console_scripts = no section header\n") == {}


def test_scripts_declared_by_a_nested_project_are_found(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "root"\n',
            "tools/helper/pyproject.toml": '[project.scripts]\nhelper = "helper.main:run"\n',
        },
    )
    assert load_scripts(tmp_path, SKIP_DIRS) == {"helper": frozenset({"helper.main"})}


def test_a_name_declared_twice_keeps_both_modules(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "a/pyproject.toml": '[project.scripts]\nserve = "a.server:main"\n',
            "b/setup.cfg": "[options.entry_points]\nconsole_scripts =\n    serve = b.server:main\n",
        },
    )
    assert load_scripts(tmp_path, SKIP_DIRS) == {"serve": frozenset({"a.server", "b.server"})}


def test_packages_installed_in_a_virtualenv_declare_nothing(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pyproject.toml": '[project.scripts]\ngreet = "pkg.cli:main"\n',
            ".venv/lib/python3.13/site-packages/other/pyproject.toml": (
                '[project.scripts]\nother = "other.cli:main"\n'
            ),
        },
    )
    assert load_scripts(tmp_path, SKIP_DIRS) == {"greet": frozenset({"pkg.cli"})}


def test_a_broken_metadata_file_does_not_hide_the_others(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pyproject.toml": '[project.scripts]\ngreet = "pkg.cli:main"\n',
            "broken/pyproject.toml": "[project\nscripts =\n",
        },
    )
    assert load_scripts(tmp_path, SKIP_DIRS) == {"greet": frozenset({"pkg.cli"})}


def test_the_scan_turns_a_declared_program_into_an_edge_and_ignores_the_rest(
    tmp_path: Path,
) -> None:
    write_tree(
        tmp_path,
        {
            "pyproject.toml": '[project.scripts]\ngreet = "pkg.cli:main"\n',
            "pkg/__init__.py": "",
            "pkg/cli.py": "def main() -> int:\n    return 0\n",
            "tests/test_x.py": (
                "import subprocess\n\n\n"
                "def test_x():\n"
                '    subprocess.run(["greet"])\n'
                '    subprocess.run(["git", "status"])\n'
            ),
        },
    )
    info = scan_repo(tmp_path)["tests/test_x.py"]
    assert info.programs == {"greet": frozenset({"pkg.cli"})}
    assert {"pkg", "pkg.cli"} <= info.deps
    assert "git" not in info.deps
