"""Reading the PROGRAM a subprocess call starts.

The unit half of console-script following. A program name is returned as
written and means nothing until the packaging metadata resolves it, so what
matters here is which positions and spellings count as a name at all.
"""

from __future__ import annotations

import ast

from testsniper.entrypoints import program_target, subprocess_modules, subprocess_programs
from testsniper.usage import is_affected


def _call(source: str) -> ast.Call:
    """The outermost call expression in a snippet."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError(f"no call in {source!r}")


def test_the_first_element_of_an_argument_vector_is_the_program() -> None:
    assert subprocess_programs(_call('subprocess.run(["greet", "--loud"])')) == {"greet"}


def test_a_tuple_command_is_read_through_every_process_starter() -> None:
    for spelling in ["subprocess.Popen", "check_output", "subprocess.call", "run"]:
        found = subprocess_programs(_call(f'{spelling}(("greet", "--loud"))'))
        assert found == {"greet"}, spelling


def test_a_program_looked_up_with_shutil_which_is_read() -> None:
    assert subprocess_programs(_call('subprocess.run([shutil.which("greet"), "-v"])')) == {"greet"}
    assert subprocess_programs(_call('subprocess.run([which("greet")])')) == {"greet"}


def test_a_one_word_string_command_is_a_program_and_a_shell_line_is_not() -> None:
    assert subprocess_programs(_call('subprocess.run("greet")')) == {"greet"}
    assert subprocess_programs(_call('subprocess.run("greet --loud", shell=True)')) == set()


def test_only_the_first_position_counts() -> None:
    """`uv run greet` starts uv; the script behind it is not followed."""
    assert subprocess_programs(_call('subprocess.run(["uv", "run", "greet"])')) == {"uv"}


def test_a_path_is_not_a_program_name() -> None:
    for source in [
        'subprocess.run(["./bin/greet"])',
        'subprocess.run(["/usr/local/bin/greet"])',
        r'subprocess.run(["bin\\greet"])',
    ]:
        assert subprocess_programs(_call(source)) == set(), source


def test_a_name_that_is_not_a_literal_is_refused() -> None:
    for source in [
        'subprocess.run([tool, "--loud"])',
        'subprocess.run([f"{tool}"])',
        "subprocess.run([*cmd])",
        "subprocess.run([])",
        "subprocess.run(cmd)",
        "subprocess.run([shutil.which(tool)])",
    ]:
        assert subprocess_programs(_call(source)) == set(), source


def test_a_call_that_does_not_start_a_process_is_not_read() -> None:
    assert subprocess_programs(_call('parser.parse(["greet"])')) == set()


def test_a_dash_m_command_is_read_as_a_module_and_names_no_program() -> None:
    call = _call('subprocess.run([sys.executable, "-m", "pkg"])')
    assert subprocess_programs(call) == set()
    assert subprocess_modules(call) == {"pkg", "pkg.__main__"}


def test_a_program_entry_never_makes_a_same_named_module_affected() -> None:
    """The entry shares an affected set with real module names, so it must
    not be mistaken for one by any of the ways that set is queried."""
    affected = {program_target("pkg")}
    assert not is_affected("pkg", affected, with_prefixes=True)
    assert not is_affected("pkg.cli", affected, with_prefixes=True)
