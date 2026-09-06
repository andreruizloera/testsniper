"""Cross-file fixture graph: which conftest fixtures reach the change, and
which test files ask for them.

A test's fixtures are not all in its file. pytest resolves each test parameter
against every applicable ``conftest.py``, nearest first, so a change can reach
a test through a fixture the file mentions only by name.

Node narrowing used to handle that with one blunt rule: if a conftest that
applies to a file is affected, run every test in that file. Safe, and far too
coarse, because one affected conftest turns narrowing off for a whole subtree
no matter how few of its fixtures the change actually touches.

This module asks the narrower question. It reads the conftest chain that
applies to a file, resolves fixture names across it the way pytest does
(nearest definition wins, and an override that requests its own name means the
one it overrode), and returns the fixture names that reach the change. Those
names go back to ``nodes.py`` to be treated exactly like an affected import,
and to ``selector.py``, which uses ``file_requests`` below to find the test
files that ask for one of them without importing anything affected. Those
files are invisible to an import graph: the fixture is the only channel.

It refuses, for the whole chain, when a conftest does something that applies to
every test underneath it regardless of what any test requests:

- an autouse fixture that reaches the change, since it runs unrequested
- a ``pytest_*`` hook that reaches the change, since hooks see every item
- module-level code that reaches the change, since it runs on import and can
  configure shared state
- ``pytest_plugins``, which can register fixtures from a module never read here
- anything the name analysis cannot read: a dynamic import, a star import of
  the change, ``globals``/``eval``/``exec``, ``request.getfixturevalue``, an
  unresolvable relative import, or a file that does not parse

A refusal is the old behavior with a reason attached, so nothing this module
does can select fewer tests than the blunt rule did.

Nothing here knows about git, pytest, or the graph that produced the affected
set. It takes paths and a set of affected module names and returns names.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from testsniper.scanner import ModuleInfo
from testsniper.usage import (
    LOCAL_IMPORT,
    declares_pytest_plugins,
    fixture_info,
    has_dynamic_import,
    index_module,
    module_bindings,
    package_parts,
    reaches,
)

# Marker standing for "this definition reads an affected import". Taint is
# resolved with one graph walk over every conftest in the chain at once, so
# each level's own affected bindings are folded into this single sentinel.
_AFFECTED = "\x00affected"


@dataclass
class FixtureVerdict:
    """What the conftest chain means for narrowing one subtree."""

    # Fixture names visible to a test file that reach the change.
    tainted: frozenset[str] = frozenset()
    # When set, narrowing must be refused for the whole subtree, for this
    # reason. ``tainted`` is meaningless then.
    block: str | None = None


@dataclass
class _Level:
    """One conftest.py in the chain, indexed."""

    relpath: str
    defs: dict[str, set[str]] = field(default_factory=dict)
    affected_names: set[str] = field(default_factory=set)
    # Requested fixture name -> the function that defines it.
    fixtures: dict[str, str] = field(default_factory=dict)
    # Defining function -> the fixture name it is requested as, for spotting
    # an override that requests the name it overrides.
    provides: dict[str, str] = field(default_factory=dict)
    autouse: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)


def _index_conftest(
    root: Path, relpath: str, affected: set[str], module: str
) -> tuple[_Level | None, str | None]:
    """Index one conftest, or explain why its subtree cannot be narrowed."""
    try:
        source = (root / relpath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=relpath)
    except (SyntaxError, ValueError, OSError):
        return None, f"{relpath} could not be parsed"

    if has_dynamic_import(tree):
        return None, f"{relpath} imports dynamically"
    if declares_pytest_plugins(tree):
        return None, f"{relpath} sets pytest_plugins, which can add fixtures from anywhere"

    pkg_parts = package_parts(relpath, module)
    bound, blocked = module_bindings(tree, pkg_parts, affected)
    if blocked:
        return None, blocked.format(where=relpath)

    level = _Level(relpath=relpath)
    level.affected_names = bound | {LOCAL_IMPORT}

    index = index_module(tree, pkg_parts, affected)
    if index.module_usage.opaque:
        return None, f"{relpath} reads names dynamically ({index.module_usage.opaque_why})"
    if reaches(index.module_usage.names, index.defs, level.affected_names):
        return None, f"module-level code in {relpath} uses an affected import"

    level.defs = index.defs
    for func in index.functions:
        info = fixture_info(func)
        if info is not None:
            level.fixtures[info.name] = info.func
            level.provides[info.func] = info.name
            if info.autouse:
                level.autouse.append(info.name)
        elif func.name.startswith("pytest_"):
            level.hooks.append(func.name)
    return level, None


def _resolve(levels: list[_Level], depth: int, name: str, *, skip_own: bool) -> str | None:
    """Resolve a name read at ``depth`` to a node in the cross-level graph.

    A name defined in the same conftest wins, except for the one case pytest
    treats specially: a fixture whose parameter is its own requested name is
    asking for the definition it overrides, one level out. Otherwise the name
    can only be a fixture from a nearer-to-root conftest; conftests do not
    share ordinary module globals.
    """
    if not skip_own and name in levels[depth].defs:
        return f"{depth}:{name}"
    for outer in range(depth - 1, -1, -1):
        if name in levels[outer].fixtures:
            return f"{outer}:{levels[outer].fixtures[name]}"
    return None


def _build_graph(levels: list[_Level]) -> dict[str, set[str]]:
    """Flatten every conftest's definitions into one name graph.

    Nodes are ``"<depth>:<function name>"``. An edge to ``_AFFECTED`` means the
    definition reads an affected import directly.
    """
    graph: dict[str, set[str]] = {}
    for depth, level in enumerate(levels):
        for name, deps in level.defs.items():
            node = f"{depth}:{name}"
            edges = graph.setdefault(node, set())
            own = level.provides.get(name)
            for dep in deps:
                if dep in level.affected_names:
                    edges.add(_AFFECTED)
                    continue
                target = _resolve(levels, depth, dep, skip_own=dep == own)
                if target is not None:
                    edges.add(target)
    return graph


def analyze_conftests(
    root: Path,
    conftests: list[str],
    affected: set[str],
    infos: dict[str, ModuleInfo],
) -> FixtureVerdict:
    """Work out which fixtures in a conftest chain reach the change.

    ``conftests`` is the chain that applies to one test file, outermost first,
    which is the order pytest resolves them in.
    """
    levels: list[_Level] = []
    for relpath in conftests:
        module = infos[relpath].module if relpath in infos else relpath
        level, block = _index_conftest(root, relpath, affected, module)
        if level is None:
            return FixtureVerdict(block=block or f"{relpath} could not be analyzed")
        levels.append(level)

    graph = _build_graph(levels)
    affected_names = {_AFFECTED}

    def reached(depth: int, func: str) -> bool:
        return reaches({f"{depth}:{func}"}, graph, affected_names)

    for depth, level in enumerate(levels):
        for name in level.autouse:
            if reached(depth, level.fixtures[name]):
                return FixtureVerdict(
                    block=f"autouse fixture {name} in {level.relpath} reaches the change"
                )
        for hook in level.hooks:
            if reached(depth, hook):
                return FixtureVerdict(
                    block=f"hook {hook} in {level.relpath} uses an affected import"
                )

    # Nearest definition wins, so walking outermost first lets a nearer
    # conftest replace what an outer one provided.
    visible: dict[str, tuple[int, str]] = {}
    for depth, level in enumerate(levels):
        for name, func in level.fixtures.items():
            visible[name] = (depth, func)

    tainted = {name for name, (depth, func) in visible.items() if reached(depth, func)}
    return FixtureVerdict(tainted=frozenset(tainted))


def conftests_for(relpath: str) -> list[str]:
    """Every conftest.py path that pytest would apply to a test file.

    Outermost first, which is the order pytest resolves fixture names in and
    the order ``analyze_conftests`` expects.
    """
    parts = PurePosixPath(relpath).parts[:-1]
    out = ["conftest.py"]
    for i in range(1, len(parts) + 1):
        out.append("/".join([*parts[:i], "conftest.py"]))
    return out


@dataclass(frozen=True)
class FileRequest:
    """Which of a set of fixture names a test file can ask for."""

    requested: frozenset[str] = frozenset()
    # Set when the file could not be read well enough to tell. Every name was
    # then reported as requested, because the safe answer to "does this file
    # use the changed fixture" is yes.
    unreadable: str | None = None


def file_requests(root: Path, relpath: str, module: str, names: frozenset[str]) -> FileRequest:
    """Which of ``names`` a test file can request.

    Deliberately coarser than the per-test analysis in ``nodes.py``: this
    decides whether a FILE is worth selecting at all, so it asks whether the
    name is read anywhere in it, by any test, fixture, helper, or mark. Node
    narrowing then decides which of its tests actually reach the fixture. A
    file this cannot read reports every name, so it is selected and its
    reason is decided by the narrower, which reads it again and refuses.
    """
    if not names:
        return FileRequest()
    try:
        source = (root / relpath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=relpath)
    except (SyntaxError, ValueError, OSError):
        return FileRequest(names, f"{relpath} could not be parsed")

    index = index_module(tree, package_parts(relpath, module), set())
    if index.module_usage.opaque:
        why = index.module_usage.opaque_why
        return FileRequest(names, f"{relpath} reads names dynamically ({why})")

    read: set[str] = set(index.module_usage.names)
    for deps in index.defs.values():
        read |= deps
    return FileRequest(frozenset(names & read))
