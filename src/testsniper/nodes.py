"""Test-node granularity: which test functions in a file reach the change.

File-level selection answers "can this test file reach the change at all,
through an import or through a conftest fixture". This module answers the
narrower question inside one already-selected file: which of its test
functions actually use what was affected.

The analysis is name usage over the file's own AST. It resolves each
module-level import to a dotted module name, marks the bindings whose target
is in the affected set, and then asks, per test function, whether any name it
reads traces back to one of those bindings. Usage propagates through the
file's own definitions, which is what makes it useful on real test files: a
test parameter is a name like any other, so a fixture defined in the file is
reached through the parameter that requests it, and ``self.helper()`` inside
a test class is reached through the sibling method it names.

A fixture the file does not define is a name like any other too. ``fixtures.py``
works out which conftest fixture NAMES reach the change, and those names are
seeded into the affected set here, so requesting one selects a test exactly
the way importing the change does.

It is deliberately easy to stop. Whenever the file does something this
analysis cannot see through, narrowing is refused for the whole file and the
reason is recorded, so the caller falls back to running every test in it.
Under-selection is the only failure mode worth preventing here; running a few
extra tests is not.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from testsniper.fixtures import analyze_conftests, conftests_for
from testsniper.scanner import ModuleInfo
from testsniper.selector import Selection
from testsniper.usage import (
    LOCAL_IMPORT,
    collect_usage,
    fixture_info,
    from_import_is_affected,
    has_dynamic_import,
    index_module,
    is_affected,
    module_bindings,
    package_parts,
    qualify,
    reaches,
)

__all__ = [
    "FileNodes",
    "Key",
    "conftests_for",
    "from_import_is_affected",
    "is_affected",
    "narrow_file",
    "narrow_selection",
]

# Key of one collected test: the "::"-joined enclosing class names (empty at
# module level) and the function name. ``TestA::TestB::test_c`` is
# ``("TestA::TestB", "test_c")``. Parametrization is not part of the key, so
# selecting a function selects every one of its parametrized cases.
Key = tuple[str, str]


@dataclass
class FileNodes:
    """Node-level verdict for one selected test file."""

    relpath: str
    narrowed: bool
    reason: str
    selected: set[Key] = field(default_factory=set)
    known: set[Key] = field(default_factory=set)

    @property
    def dropped(self) -> int:
        """Test functions excluded by narrowing (zero when not narrowed)."""
        if not self.narrowed:
            return 0
        return len(self.known) - len(self.selected)

    def keeps(self, key: Key) -> bool:
        """Whether a collected test should run.

        An unrecognized key is always kept. The AST sees ordinary test
        functions; anything else pytest collected from this file (a doctest,
        an item from a custom collector) is not something this analysis
        reasoned about, so it is not something it may drop.
        """
        if not self.narrowed:
            return True
        if key not in self.known:
            return True
        return key in self.selected


def _test_functions(tree: ast.Module) -> list[tuple[Key, ast.AST, tuple[str, ...]]]:
    """Collected test functions, as (key, node, enclosing class path).

    Follows pytest's default convention: module-level ``test*`` functions and
    ``test*`` methods on ``Test*`` classes, including nested ones.
    """
    found: list[tuple[Key, ast.AST, tuple[str, ...]]] = []

    def walk(body: list[ast.stmt], classes: tuple[str, ...]) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("test"):
                    found.append((("::".join(classes), node.name), node, classes))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                walk(node.body, (*classes, node.name))

    walk(tree.body, ())
    return found


def _narrowed_reason(fixtures: Iterable[str]) -> str:
    count = len(set(fixtures))
    if not count:
        return "narrowed by name usage"
    noun = "fixture" if count == 1 else "fixtures"
    return f"narrowed by name usage and {count} affected conftest {noun}"


def narrow_file(
    root: Path,
    relpath: str,
    affected: set[str],
    module: str,
    fixtures: Iterable[str] = (),
) -> FileNodes:
    """Decide which test functions in one file reach the affected modules.

    ``fixtures`` names conftest fixtures that reach the change. They are
    treated exactly like affected import bindings, so requesting one, directly
    or through another fixture, selects the test.
    """
    try:
        source = (root / relpath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=relpath)
    except (SyntaxError, ValueError, OSError):
        return FileNodes(relpath, False, "the file could not be parsed")

    pkg_parts = package_parts(relpath, module)

    if has_dynamic_import(tree):
        return FileNodes(relpath, False, "the file imports dynamically")

    affected_names, blocked = module_bindings(tree, pkg_parts, affected)
    if blocked:
        return FileNodes(relpath, False, blocked.format(where="this file"))
    affected_names.add(LOCAL_IMPORT)
    tainted_fixtures = set(fixtures)
    affected_names |= tainted_fixtures

    index = index_module(tree, pkg_parts, affected)
    if index.module_usage.opaque:
        why = index.module_usage.opaque_why
        return FileNodes(relpath, False, f"the file reads names dynamically ({why})")
    if reaches(index.module_usage.names, index.defs, affected_names):
        return FileNodes(relpath, False, "module-level code uses an affected import")

    # An autouse fixture runs for tests that never name it, so one that
    # reaches the change puts every test in its scope back in play.
    for func in index.functions:
        info = fixture_info(func)
        if info is not None and info.autouse and reaches({func.name}, index.defs, affected_names):
            return FileNodes(
                relpath, False, f"autouse fixture {info.name} in this file uses an affected import"
            )
    autouse_classes: set[str] = set()
    for prefix, methods in index.methods.items():
        for method in methods:
            info = fixture_info(method)
            if info is None or not info.autouse:
                continue
            if reaches({f"{prefix}self.{method.name}"}, index.defs, affected_names):
                autouse_classes.add(prefix.removesuffix("::"))

    nodes = FileNodes(relpath, True, _narrowed_reason(tainted_fixtures))
    for key, node, classes in _test_functions(tree):
        nodes.known.add(key)
        usage = collect_usage(node, pkg_parts, affected)
        prefix = "::".join(classes) + "::" if classes else ""
        names = qualify(usage.names, prefix)
        if classes:
            # The outermost class's shared names already absorb its nested
            # classes, so one lookup covers every depth.
            outer = index.class_shared.get(f"{classes[0]}::")
            if outer is not None:
                names |= qualify(outer.names, f"{classes[0]}::")
        path = "::".join(classes)
        in_autouse_class = any(
            path == cls or path.startswith(f"{cls}::") for cls in autouse_classes
        )
        if in_autouse_class or reaches(names, index.defs, affected_names):
            nodes.selected.add(key)

    if not nodes.known:
        return FileNodes(relpath, False, "no test functions were found by the AST")
    return nodes


def narrow_selection(
    root: Path,
    selection: Selection,
    infos: dict[str, ModuleInfo],
) -> dict[str, FileNodes]:
    """Apply node narrowing to every file in a file-level selection.

    Files selected for a reason the analysis cannot refine (the test file
    itself changed, always_run, a changed conftest subtree) keep all of their
    tests; the selection marks those ``narrowable=False``. When a conftest
    that applies to a file is itself affected, the fixture graph decides: if
    the change reaches that conftest only through fixtures, those fixture
    names are handed to ``narrow_file`` and narrowing continues; if it reaches
    something that applies to every test underneath regardless of what any
    test names, narrowing is refused with that reason.

    The verdicts are the ones selection already computed, when it computed
    them, so the file-level and node-level answers come from one reading of
    the conftest chain rather than two.
    """
    out: dict[str, FileNodes] = {}
    if selection.select_all:
        for test in selection.tests:
            out[test.relpath] = FileNodes(test.relpath, False, "everything is selected")
        return out

    known_conftests = {rel for rel in infos if PurePosixPath(rel).name == "conftest.py"}

    for test in selection.tests:
        rel = test.relpath
        if test.distance == 0:
            out[rel] = FileNodes(rel, False, "the test file itself changed")
            continue

        chain = tuple(c for c in conftests_for(rel) if c in known_conftests)
        tainted: frozenset[str] = frozenset()
        if any(c in selection.affected_files for c in chain):
            if chain not in selection.fixture_verdicts:
                selection.fixture_verdicts[chain] = analyze_conftests(
                    root, list(chain), selection.affected_modules, infos
                )
            verdict = selection.fixture_verdicts[chain]
            # A block outranks the file's own selection reason: it is the more
            # specific answer to "why is all of this file running".
            if verdict.block is not None:
                out[rel] = FileNodes(rel, False, verdict.block)
                continue
            tainted = verdict.tainted

        if test.whole_file is not None:
            out[rel] = FileNodes(rel, False, test.whole_file)
            continue

        module = infos[rel].module if rel in infos else rel
        out[rel] = narrow_file(root, rel, selection.affected_modules, module, fixtures=tainted)
    return out
