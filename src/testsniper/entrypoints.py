"""Subprocess invocations of the project's own code.

The import graph is the model everything else here is built on: a test
depends on a module because some chain of ``import`` statements connects
them. A test that RUNS the project instead of importing it has no such
chain, and is invisible to every analysis in this package.

    subprocess.run([sys.executable, "-m", "mytool", "--list"], cwd=repo)

Nothing in that statement is an import. The test reads ``sys.executable``
and two string literals, and the module it actually exercises appears only
as the contents of one of them. This module reads that string back out.

It is deliberately narrow. Only a ``-m`` immediately followed by a string
literal counts, and only inside a call whose name is one of the standard
``subprocess`` entry points. A module name built at runtime, or passed
through a variable, is not matched and not guessed at: the result would be
an under-selection, which is the one failure mode this package treats as
worth refusing over.

What it does NOT see is recorded in ROADMAP.md rather than papered over.
The largest gap is a console script (``subprocess.run(["mytool", ...])``),
which needs the project's ``[project.scripts]`` table to resolve a bare
name to a module.

Nothing here does I/O. Callers pass in a parsed tree and get back names.
"""

from __future__ import annotations

import ast

__all__ = ["SUBPROCESS_FUNCTIONS", "subprocess_modules", "tree_subprocess_modules"]

# The standard library's ways of starting a process. Matched on the
# attribute or bare name, so both ``subprocess.run(...)`` and a
# ``from subprocess import run`` are seen. Matching this loosely is safe:
# the payoff is a module name that has to appear in the repository's own
# scan to mean anything, so a same-named call to something else
# contributes a dotted name that resolves to no file.
SUBPROCESS_FUNCTIONS: frozenset[str] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)


def _is_subprocess_call(func: ast.expr) -> bool:
    """Whether this call expression starts a process."""
    if isinstance(func, ast.Attribute):
        return func.attr in SUBPROCESS_FUNCTIONS
    if isinstance(func, ast.Name):
        return func.id in SUBPROCESS_FUNCTIONS
    return False


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


def tree_subprocess_modules(node: ast.AST) -> set[str]:
    """Every ``python -m`` target anywhere inside a syntax tree."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            found |= subprocess_modules(child)
    return found
