"""Subprocess invocations of the project's own code.

The import graph is the model everything else here is built on: a test
depends on a module because some chain of ``import`` statements connects
them. A test that RUNS the project instead of importing it has no such
chain, and is invisible to every analysis in this package.

    subprocess.run([sys.executable, "-m", "mytool", "--list"], cwd=repo)
    subprocess.run(["mytool", "--list"], cwd=repo)

Nothing in either statement is an import. The test reads ``sys.executable``
and some string literals, and the code it actually exercises appears only
as the contents of one of them. This module reads that string back out.

The two forms name different things, so they come back differently. A
``-m`` target IS a module name. A bare program name is not: ``mytool`` is a
console script an installer generated from one line of packaging metadata,
and only that metadata says which module it imports. So a program name is
returned exactly as written, and ``scripts.py`` resolves it once per
repository. A program the repository does not declare (``git``, ``python``)
resolves to nothing and costs nothing.

It is deliberately narrow. Only a ``-m`` immediately followed by a string
literal counts, only a program name written as a literal in the first
position of the command (or passed through ``shutil.which``) counts, and
only inside a call whose name is one of the standard ``subprocess`` entry
points. A name built at runtime, or passed through a variable, is not
matched and not guessed at: the result would be an under-selection, which
is the one failure mode this package treats as worth refusing over.

Nothing here does I/O. Callers pass in a parsed tree and get back names.
"""

from __future__ import annotations

import ast

__all__ = [
    "SUBPROCESS_FUNCTIONS",
    "program_target",
    "subprocess_modules",
    "subprocess_programs",
    "tree_subprocess_modules",
]

# The standard library's ways of starting a process. Matched on the
# attribute or bare name, so both ``subprocess.run(...)`` and a
# ``from subprocess import run`` are seen. Matching this loosely is safe:
# the payoff is a module name that has to appear in the repository's own
# scan to mean anything, so a same-named call to something else
# contributes a dotted name that resolves to no file.
SUBPROCESS_FUNCTIONS: frozenset[str] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)

# The prefix of the entry an affected set carries for a program whose
# console script imports something affected. The NUL byte means it can never
# equal a real module name or start with one.
_PROGRAM_TARGET = "\x00program:"


def program_target(name: str) -> str:
    """The affected-set entry that stands for running the program ``name``."""
    return f"{_PROGRAM_TARGET}{name}"


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_subprocess_call(func: ast.expr) -> bool:
    """Whether this call expression starts a process."""
    return _call_name(func) in SUBPROCESS_FUNCTIONS


def _argv_elements(call: ast.Call) -> list[ast.expr]:
    """The elements of the argument-vector literal, if there is one.

    ``subprocess.run`` takes the command as its first positional argument.
    A string command (``shell=True``) is not handled: splitting a shell
    line correctly is a different problem and getting it wrong here would
    invent a dependency rather than miss one.
    """
    if not call.args:
        return []
    first = call.args[0]
    if isinstance(first, (ast.List, ast.Tuple)):
        return list(first.elts)
    return []


def _constant_str(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def subprocess_modules(call: ast.Call) -> set[str]:
    """Dotted modules a subprocess call executes via ``python -m``.

    Returns the module named after ``-m`` and, for the package case, its
    ``__main__`` submodule: ``python -m pkg`` imports ``pkg`` and then
    executes ``pkg/__main__.py``, and it is the latter that holds the code
    the process actually runs. When the target is a plain module rather
    than a package, the extra ``pkg.__main__`` name simply resolves to no
    file and costs nothing.

    An empty set is the answer for everything this cannot read, which is
    most things. That is the intended bias.
    """
    if not _is_subprocess_call(call.func):
        return set()
    elements = _argv_elements(call)
    found: set[str] = set()
    for index, element in enumerate(elements[:-1]):
        if _constant_str(element) != "-m":
            continue
        target = _constant_str(elements[index + 1])
        # A module name is dotted identifiers and nothing else. This also
        # rejects the empty string and anything with a path separator.
        if target and all(part.isidentifier() for part in target.split(".")):
            found.add(target)
            found.add(f"{target}.__main__")
    return found


def _program_name(node: ast.expr) -> str | None:
    """A program written as a bare name, or looked up with ``shutil.which``.

    A path (``./bin/mytool``, ``/usr/local/bin/mytool``) is refused: it names
    a file, and which declared script a file is cannot be read from the
    source. So is anything containing whitespace, which is a shell line
    rather than a name.
    """
    if isinstance(node, ast.Call) and node.args and _call_name(node.func) == "which":
        node = node.args[0]
    name = _constant_str(node)
    if not name or any(char.isspace() or char in "/\\" for char in name):
        return None
    return name


def subprocess_programs(call: ast.Call) -> set[str]:
    """The program a subprocess call starts, when it is written as a name.

    That is the first element of an argument-vector literal, or a whole
    string command of one word, since ``subprocess.run("mytool")`` starts the
    program ``mytool`` with or without a shell. The name is returned as
    written. Whether it is a console script of this repository, and which
    module that script imports, is decided by the caller against the
    packaging metadata.

    Only the first position counts, so ``["uv", "run", "mytool"]`` is read as
    starting ``uv`` and the script behind it is not followed. Reading every
    element would follow it, and would also bind a test to every declared
    name it merely passes as an argument.
    """
    if not _is_subprocess_call(call.func) or not call.args:
        return set()
    first = call.args[0]
    if isinstance(first, (ast.List, ast.Tuple)):
        if not first.elts:
            return set()
        first = first.elts[0]
    name = _program_name(first)
    return {name} if name is not None else set()


def tree_subprocess_modules(node: ast.AST) -> set[str]:
    """Every ``python -m`` target anywhere inside a syntax tree."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            found |= subprocess_modules(child)
    return found
