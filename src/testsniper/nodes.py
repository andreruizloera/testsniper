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
    DEF_TYPES,
    LOCAL_IMPORT,
    SUBPROCESS_ENTRY,
    FuncDef,
    SymbolMap,
    changed_imports,
    collect_usage,
    fixture_info,
    from_import_is_affected,
    has_dynamic_import,
    index_module,
    is_affected,
    module_bindings,
    module_statements,
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


def _test_functions(
    body: list[ast.stmt], classes: tuple[str, ...] = ()
) -> list[tuple[Key, ast.AST, tuple[str, ...]]]:
    """Collected test functions, as (key, node, enclosing class path).

    Follows pytest's default convention: module-level ``test*`` functions and
    ``test*`` methods on ``Test*`` classes, including nested ones. ``classes``
    is the class path ``body`` sits in, so a single class can be asked for its
    own tests.
    """
    found: list[tuple[Key, ast.AST, tuple[str, ...]]] = []
    for node in body:
        if isinstance(node, FuncDef):
            if node.name.startswith("test"):
                found.append((("::".join(classes), node.name), node, classes))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            found.extend(_test_functions(node.body, (*classes, node.name)))
    return found


def _narrowed_reason(fixtures: Iterable[str], diffed: bool) -> str:
    parts = ["its own diff"] if diffed else []
    parts.append("name usage")
    count = len(set(fixtures))
    if count:
        noun = "fixture" if count == 1 else "fixtures"
        parts.append(f"{count} affected conftest {noun}")
    if len(parts) > 1:
        parts = [", ".join(parts[:-1]) + " and " + parts[-1]]
    return f"narrowed by {parts[0]}"


@dataclass
class _FileDiff:
    """What a changed test file's own diff means for its own tests.

    ``changed_names`` are the names a reader of the file can use to reach the
    change: the definitions whose parsed syntax moved, the names bound by an
    import statement the diff touched, and the names it deleted, which no
    graph walk can find because the node is gone. ``changed_tests`` are the
    test functions that ARE the change, which nothing in the file reads by
    name and which therefore have to be carried separately.
    """

    changed_names: frozenset[str] = frozenset()
    changed_tests: frozenset[Key] = frozenset()
    block: str | None = None


def _class_shell(node: ast.ClassDef) -> tuple[str, ...]:
    """Everything about a class except the definitions inside it.

    Bases, keywords, decorators, and class-body statements are shared by every
    method, so a move in any of them is a move for the whole class. The
    methods are compared one at a time instead.
    """
    return (
        node.name,
        *(ast.dump(b) for b in node.bases),
        *(ast.dump(k) for k in node.keywords),
        *(ast.dump(d) for d in node.decorator_list),
        *(ast.dump(s) for s in node.body if not isinstance(s, DEF_TYPES)),
    )


def _compare_defs(
    old_body: list[ast.stmt],
    new_body: list[ast.stmt],
    classes: tuple[str, ...],
    names: set[str],
    tests: set[Key],
) -> str | None:
    """Record what one scope's diff moved, or return why it cannot be read.

    Recurses into a ``Test*`` class whose shell is unchanged, so editing one
    method selects that method rather than its whole class.
    """
    prefix = "::".join(classes) + "::" if classes else ""
    old_defs = {s.name: s for s in old_body if isinstance(s, DEF_TYPES)}
    new_defs = {s.name: s for s in new_body if isinstance(s, DEF_TYPES)}

    def mark(name: str, node: ast.stmt) -> None:
        names.add(f"{prefix}self.{name}" if classes else name)
        tests.update(key for key, _, _ in _test_functions([node], classes))

    for name, node in new_defs.items():
        previous = old_defs.get(name)
        if (
            isinstance(node, ast.ClassDef)
            and isinstance(previous, ast.ClassDef)
            and name.startswith("Test")
            and _class_shell(previous) == _class_shell(node)
        ):
            block = _compare_defs(previous.body, node.body, (*classes, name), names, tests)
            if block is not None:
                return block
            continue
        if previous is not None and ast.dump(previous) == ast.dump(node):
            continue
        if isinstance(node, FuncDef) and name.startswith("pytest_") and fixture_info(node) is None:
            return f"hook {name} in this file changed; hooks see every collected item"
        mark(name, node)

    for name, node in old_defs.items():
        if name in new_defs:
            continue
        if isinstance(node, FuncDef):
            info = fixture_info(node)
            if info is not None and info.autouse:
                return f"autouse fixture {info.name} was removed from this file"
            if info is None and name.startswith("pytest_"):
                return f"hook {name} was removed from this file"
        names.add(f"{prefix}self.{name}" if classes else name)
    return None


def _diff_test_file(relpath: str, old_source: str | None, tree: ast.Module) -> _FileDiff:
    """Which of a changed test file's own definitions the diff touched.

    Definitions are compared as PARSED SYNTAX, so reflowing a line or editing
    a comment inside a test selects nothing. Anything the comparison cannot
    localize is a block, which is the old whole-file behavior with a reason.
    """
    if old_source is None:
        return _FileDiff(block="this file is new; there is no previous content to compare against")
    try:
        old = ast.parse(old_source, filename=relpath)
    except (SyntaxError, ValueError):
        return _FileDiff(block="the previous content of this file could not be parsed")
    if has_dynamic_import(old):
        return _FileDiff(block="the previous content of this file imports dynamically")
    if module_statements(old) != module_statements(tree):
        return _FileDiff(block="module-level code in this file changed; it runs on import")

    names, star_moved = changed_imports(old, tree)
    if star_moved:
        return _FileDiff(block="a star import in this file changed")

    tests: set[Key] = set()
    block = _compare_defs(old.body, tree.body, (), names, tests)
    if block is not None:
        return _FileDiff(block=block)
    return _FileDiff(changed_names=frozenset(names), changed_tests=frozenset(tests))


def narrow_file(
    root: Path,
    relpath: str,
    affected: set[str],
    module: str,
    fixtures: Iterable[str] = (),
    old_source: str | None = None,
    is_changed: bool = False,
    symbols: SymbolMap | None = None,
) -> FileNodes:
    """Decide which test functions in one file reach the affected modules.

    ``fixtures`` names conftest fixtures that reach the change. They are
    treated exactly like affected import bindings, so requesting one, directly
    or through another fixture, selects the test.

    ``is_changed`` says the file is itself in the change set, in which case
    ``old_source`` is its content at the revision the run compares against
    (``None`` when there is none) and its own diff is a second source of
    taint: the tests it moved are selected, and the helpers and fixtures it
    moved select the tests that read them.

    ``symbols`` narrows the affected set one unit further, from the changed
    MODULE to the symbols in it the change reaches, so ``from pricing.core
    import line_total`` stops counting as affected when only
    ``price_with_tax`` moved. A module absent from the map keeps the older
    answer, which is that importing any name from it is affected.
    """
    try:
        source = (root / relpath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=relpath)
    except (SyntaxError, ValueError, OSError):
        return FileNodes(relpath, False, "the file could not be parsed")

    pkg_parts = package_parts(relpath, module)

    if has_dynamic_import(tree):
        return FileNodes(relpath, False, "the file imports dynamically")

    affected_names, blocked = module_bindings(tree, pkg_parts, affected, symbols)
    if blocked:
        return FileNodes(relpath, False, blocked.format(where="this file"))
    affected_names.add(LOCAL_IMPORT)
    affected_names.add(SUBPROCESS_ENTRY)
    tainted_fixtures = set(fixtures)
    affected_names |= tainted_fixtures

    index = index_module(tree, pkg_parts, affected, symbols)
    if index.module_usage.opaque:
        why = index.module_usage.opaque_why
        return FileNodes(relpath, False, f"the file reads names dynamically ({why})")
    if reaches(index.module_usage.names, index.defs, affected_names):
        return FileNodes(relpath, False, "module-level code uses an affected import")

    diff: _FileDiff | None = None
    if is_changed:
        diff = _diff_test_file(relpath, old_source, tree)
        if diff.block is not None:
            return FileNodes(relpath, False, diff.block)
        changed_names = set(diff.changed_names)
        if reaches(index.module_usage.names, index.defs, changed_names):
            return FileNodes(
                relpath, False, "module-level code in this file reads something the diff changed"
            )
        for func in index.functions:
            info = fixture_info(func)
            if (
                info is not None
                and info.autouse
                and reaches({func.name}, index.defs, changed_names)
            ):
                return FileNodes(
                    relpath, False, f"autouse fixture {info.name} in this file changed"
                )
        affected_names |= changed_names

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

    changed_tests = diff.changed_tests if diff is not None else frozenset()
    nodes = FileNodes(relpath, True, _narrowed_reason(tainted_fixtures, diff is not None))
    for key, node, classes in _test_functions(tree.body):
        nodes.known.add(key)
        usage = collect_usage(node, pkg_parts, affected, symbols)
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
        if key in changed_tests or in_autouse_class or reaches(names, index.defs, affected_names):
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

    Files selected for a reason the analysis cannot refine (always_run, a
    changed conftest subtree) keep all of their tests; the selection marks
    those ``narrowable=False``. A test file that is itself in the change set
    is refined by its own diff when the selection recorded its previous
    content, and runs whole when it did not. When a conftest
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
        # A changed test file with no previous content recorded cannot be
        # diffed, so it keeps the older answer and runs whole.
        is_changed = test.distance == 0
        if is_changed and rel not in selection.changed_test_sources:
            out[rel] = FileNodes(rel, False, "the test file itself changed")
            continue

        chain = tuple(c for c in conftests_for(rel) if c in known_conftests)
        tainted: frozenset[str] = frozenset()
        # A verdict selection already computed covers both ways a conftest can
        # carry the change: reading something affected, or having changed
        # itself. Only the first can be recomputed here, so a cached verdict
        # always wins over a fresh one.
        if chain in selection.fixture_verdicts or any(c in selection.affected_files for c in chain):
            if chain not in selection.fixture_verdicts:
                selection.fixture_verdicts[chain] = analyze_conftests(
                    root,
                    list(chain),
                    selection.affected_modules,
                    infos,
                    symbols=selection.affected_symbols,
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
        out[rel] = narrow_file(
            root,
            rel,
            selection.affected_modules,
            module,
            fixtures=tainted,
            old_source=selection.changed_test_sources.get(rel),
            is_changed=is_changed,
            symbols=selection.affected_symbols,
        )
    return out
