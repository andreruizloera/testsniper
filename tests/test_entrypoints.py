"""Reading a `python -m` target back out of a subprocess call.

These are the unit half. Everything here is about what the reader REFUSES
as much as what it matches, because a wrong match here invents a
dependency and a missed one loses a test.
"""

from __future__ import annotations

import ast

from testsniper.entrypoints import subprocess_modules, tree_subprocess_modules


def _call(source: str) -> ast.Call:
    """The first call expression in a snippet."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError(f"no call in {source!r}")


def test_a_dash_m_target_is_read_with_its_main_submodule() -> None:
    found = subprocess_modules(_call('subprocess.run([sys.executable, "-m", "mytool", "--list"])'))
    assert found == {"mytool", "mytool.__main__"}


def test_a_dotted_target_is_read_whole() -> None:
    found = subprocess_modules(_call('subprocess.run([sys.executable, "-m", "a.b"])'))
    assert found == {"a.b", "a.b.__main__"}


def test_a_bare_imported_run_is_matched() -> None:
    """`from subprocess import run` leaves no attribute to match on."""
    found = subprocess_modules(_call('run([sys.executable, "-m", "mytool"])'))
    assert found == {"mytool", "mytool.__main__"}


def test_popen_and_check_output_are_matched() -> None:
    for spelling in ("subprocess.Popen", "subprocess.check_output", "subprocess.check_call"):
        found = subprocess_modules(_call(f'{spelling}([sys.executable, "-m", "mytool"])'))
        assert found == {"mytool", "mytool.__main__"}, spelling


def test_a_tuple_command_is_read_like_a_list() -> None:
    found = subprocess_modules(_call('subprocess.run((sys.executable, "-m", "mytool"))'))
    assert found == {"mytool", "mytool.__main__"}


def test_a_module_name_held_in_a_variable_is_refused() -> None:
    """The name is not in the syntax, so there is nothing honest to return."""
    assert subprocess_modules(_call('subprocess.run([sys.executable, "-m", mod])')) == set()


def test_an_f_string_target_is_refused() -> None:
    assert subprocess_modules(_call('subprocess.run([sys.executable, "-m", f"{pkg}"])')) == set()


def test_a_command_with_no_dash_m_yields_nothing() -> None:
    assert subprocess_modules(_call('subprocess.run([sys.executable, "script.py"])')) == set()


def test_a_shell_string_command_is_refused() -> None:
    """Splitting a shell line is a different problem and is not guessed at."""
    assert subprocess_modules(_call('subprocess.run("python -m mytool", shell=True)')) == set()


def test_a_trailing_dash_m_does_not_run_off_the_end() -> None:
    assert subprocess_modules(_call('subprocess.run([sys.executable, "-m"])')) == set()


def test_a_target_that_is_not_an_identifier_is_refused() -> None:
    for bad in ("not-a-module", "", "a..b", "path/to/thing.py", "3bad"):
        call = _call(f'subprocess.run([sys.executable, "-m", {bad!r}])')
        assert subprocess_modules(call) == set(), bad


def test_a_non_subprocess_call_is_not_matched() -> None:
    """`-m` in an unrelated call is not a process start."""
    assert subprocess_modules(_call('parser.parse([sys.executable, "-m", "mytool"])')) == set()


def test_several_targets_in_one_tree_are_all_found() -> None:
    source = (
        "def t():\n"
        '    subprocess.run([sys.executable, "-m", "one"])\n'
        '    subprocess.run([sys.executable, "-m", "two", "--flag"])\n'
    )
    assert tree_subprocess_modules(ast.parse(source)) == {
        "one",
        "one.__main__",
        "two",
        "two.__main__",
    }


def test_a_tree_with_no_subprocess_call_is_empty() -> None:
    tree = ast.parse("import os\n\ndef t():\n    return os.getcwd()\n")
    assert tree_subprocess_modules(tree) == set()
