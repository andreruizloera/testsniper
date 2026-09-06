"""Test-node granularity: which test functions in a file reach the change.

File-level selection answers "can this test file reach the change at all,
through imports". This module answers the narrower question inside one
already-selected file: which of its test functions actually use the imports
that were affected.

The analysis is name usage over the file's own AST. It resolves each
module-level import to a dotted module name, marks the bindings whose target
is in the affected set, and then asks, per test function, whether any name it
reads traces back to one of those bindings. Usage propagates through the
file's own definitions, which is what makes it useful on real test files: a
test parameter is a name like any other, so a fixture defined in the file is
reached through the parameter that requests it, and ``self.helper()`` inside
a test class is reached through the sibling method it names.

It is deliberately easy to stop. Whenever the file does something this
analysis cannot see through, narrowing is refused for the whole file and the
reason is recorded, so the caller falls back to running every test in it.
Under-selection is the only failure mode worth preventing here; running a few
extra tests is not.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from testsniper.scanner import ModuleInfo, resolve_from
from testsniper.selector import Selection

# Key of one collected test: the "::"-joined enclosing class names (empty at
# module level) and the function name. ``TestA::TestB::test_c`` is
# ``("TestA::TestB", "test_c")``. Parametrization is not part of the key, so
# selecting a function selects every one of its parametrized cases.
Key = tuple[str, str]

# Pseudo-name recorded when a function imports an affected module locally. It
# is seeded into the affected-name set, so a function-local import selects its
# own function through the ordinary name-usage path and nothing else.
LOCAL_IMPORT = "\x00local-import"

# Builtins that make name usage unreadable. getattr is excluded on purpose: it
# is far too common in ordinary test code to carry any signal.
_OPAQUE_BUILTINS: frozenset[str] = frozenset({"globals", "locals", "eval", "exec"})


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


def is_affected(dotted: str, affected: set[str], *, with_prefixes: bool = False) -> bool:
    """Whether importing ``dotted`` can reach an affected module.

    True when the module itself is affected, or when an affected module sits
    underneath it as a submodule. ``with_prefixes`` additionally counts the
    parent packages that a plain ``import a.b.c`` also executes.
    """
    if dotted in affected:
        return True
    prefix = f"{dotted}."
    if any(name.startswith(prefix) for name in affected):
        return True
    if with_prefixes:
        parts = dotted.split(".")
        return any(".".join(parts[:i]) in affected for i in range(1, len(parts)))
    return False


def from_import_is_affected(module: str, name: str, affected: set[str]) -> bool:
    """Whether ``from <module> import <name>`` binds something affected.

    The module must be affected *exactly*, not merely be a package that
    contains an affected submodule: ``from pkg import other`` does not reach
    ``pkg.changed``. What does reach it is the submodule itself
    (``from pkg import changed``), or a package whose own ``__init__`` is in
    the closure because it re-exports from the change.
    """
    return module in affected or is_affected(f"{module}.{name}", affected)


def _qualify(names: set[str], prefix: str) -> set[str]:
    """Scope ``self.x`` pseudo-names to the class path they were read in."""
    if not prefix:
        return set(names)
    return {f"{prefix}{n}" if n.startswith("self.") else n for n in names}


class _Usage:
    """The names a syntax tree reads, plus the flag that stops narrowing."""

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.opaque = False

    def merge(self, other: _Usage) -> None:
        self.names |= other.names
        self.opaque = self.opaque or other.opaque


def _collect_usage(node: ast.AST, pkg_parts: list[str], affected: set[str]) -> _Usage:
    """Every name read anywhere inside a syntax tree.

    Parameters count as names, so a fixture defined in the same file is
    reached from the test that requests it. ``self.method`` is recorded as a
    pseudo-name so sibling methods resolve later. A local import of an
    affected module contributes LOCAL_IMPORT.
    """
    usage = _Usage()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            usage.names.add(child.id)
            if child.id in _OPAQUE_BUILTINS:
                usage.opaque = True
        elif isinstance(child, ast.arg):
            usage.names.add(child.arg)
        elif isinstance(child, ast.Attribute):
            if isinstance(child.value, ast.Name) and child.value.id == "self":
                usage.names.add(f"self.{child.attr}")
        elif isinstance(child, ast.Import):
            for alias in child.names:
                if is_affected(alias.name, affected, with_prefixes=True):
                    usage.names.add(LOCAL_IMPORT)
        elif isinstance(child, ast.ImportFrom):
            resolved, unresolved = resolve_from(child, pkg_parts)
            if resolved is None:
                if unresolved:
                    usage.names.add(LOCAL_IMPORT)
                continue
            for alias in child.names:
                if alias.name == "*":
                    if resolved in affected:
                        usage.names.add(LOCAL_IMPORT)
                elif from_import_is_affected(resolved, alias.name, affected):
                    usage.names.add(LOCAL_IMPORT)
    return usage


def _module_bindings(
    tree: ast.Module, pkg_parts: list[str], affected: set[str]
) -> tuple[set[str], str | None]:
    """Module-level import bindings whose target is affected.

    Returns the bound names, and a blocking reason when an import cannot be
    attributed to individual names precisely enough to narrow on.
    """
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    if is_affected(alias.name, affected):
                        bound.add(alias.asname)
                elif is_affected(alias.name, affected, with_prefixes=True):
                    bound.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            resolved, unresolved = resolve_from(node, pkg_parts)
            if unresolved:
                return bound, "a relative import in this file could not be resolved"
            if resolved is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    if resolved in affected:
                        return bound, f"star import from affected module {resolved}"
                    continue
                if from_import_is_affected(resolved, alias.name, affected):
                    bound.add(alias.asname or alias.name)
    return bound, None


def _has_dynamic_import(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "__import__":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            return True
    return False


def _reaches(start: set[str], defs: dict[str, set[str]], affected_names: set[str]) -> bool:
    """Whether any name reachable from ``start`` is an affected binding.

    ``defs`` maps a name defined in this file (a helper, a fixture, a sibling
    method as ``Class::self.name``) to the names its body reads, so usage
    propagates through the file's own definitions. The visited set makes
    recursion and mutual recursion terminate.
    """
    seen: set[str] = set()
    stack = list(start)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in affected_names:
            return True
        stack.extend(defs.get(name, ()))
    return False


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


def _package_parts(relpath: str, module: str) -> list[str]:
    """The dotted package a file sits in, for resolving relative imports."""
    parts = module.split(".")
    if PurePosixPath(relpath).name == "__init__.py":
        return parts
    return parts[:-1]


def narrow_file(root: Path, relpath: str, affected: set[str], module: str) -> FileNodes:
    """Decide which test functions in one file reach the affected modules."""
    try:
        source = (root / relpath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=relpath)
    except (SyntaxError, ValueError, OSError):
        return FileNodes(relpath, False, "the file could not be parsed")

    pkg_parts = _package_parts(relpath, module)

    if _has_dynamic_import(tree):
        return FileNodes(relpath, False, "the file imports dynamically")

    affected_names, blocked = _module_bindings(tree, pkg_parts, affected)
    if blocked:
        return FileNodes(relpath, False, blocked)
    affected_names.add(LOCAL_IMPORT)

    # Names defined in this file, mapped to the names their bodies read, so a
    # test reaches an affected import through its own helpers and fixtures.
    defs: dict[str, set[str]] = {}
    module_usage = _Usage()

    def record_class(node: ast.ClassDef, prefix: str) -> _Usage:
        """Index one class's methods and return the names its body reads."""
        shared = _Usage()
        method_names: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                usage = _collect_usage(stmt, pkg_parts, affected)
                method_names.append(stmt.name)
                defs.setdefault(f"{prefix}self.{stmt.name}", set()).update(
                    _qualify(usage.names, prefix)
                )
                shared.opaque = shared.opaque or usage.opaque
            elif isinstance(stmt, ast.ClassDef):
                shared.merge(record_class(stmt, f"{prefix}{stmt.name}::"))
            elif not isinstance(stmt, ast.Import | ast.ImportFrom):
                shared.merge(_collect_usage(stmt, pkg_parts, affected))
        for decorator in node.decorator_list:
            shared.merge(_collect_usage(decorator, pkg_parts, affected))
        # Class-body state is shared by every method defined on the class.
        for name in method_names:
            defs.setdefault(f"{prefix}self.{name}", set()).update(_qualify(shared.names, prefix))
        return shared

    class_shared: dict[str, _Usage] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            usage = _collect_usage(stmt, pkg_parts, affected)
            defs.setdefault(stmt.name, set()).update(usage.names)
            module_usage.opaque = module_usage.opaque or usage.opaque
        elif isinstance(stmt, ast.ClassDef):
            class_shared[stmt.name] = record_class(stmt, f"{stmt.name}::")
        elif not isinstance(stmt, ast.Import | ast.ImportFrom):
            module_usage.merge(_collect_usage(stmt, pkg_parts, affected))

    for shared in class_shared.values():
        module_usage.opaque = module_usage.opaque or shared.opaque
    if module_usage.opaque:
        return FileNodes(relpath, False, "the file reads names dynamically (globals/eval/exec)")
    if _reaches(module_usage.names, defs, affected_names):
        return FileNodes(relpath, False, "module-level code uses an affected import")

    nodes = FileNodes(relpath, True, "narrowed by name usage")
    for key, node, classes in _test_functions(tree):
        nodes.known.add(key)
        usage = _collect_usage(node, pkg_parts, affected)
        prefix = "::".join(classes) + "::" if classes else ""
        names = _qualify(usage.names, prefix)
        if classes:
            # The outermost class's shared names already absorb its nested
            # classes, so one lookup covers every depth.
            outer = class_shared.get(classes[0])
            if outer is not None:
                names |= _qualify(outer.names, f"{classes[0]}::")
        if _reaches(names, defs, affected_names):
            nodes.selected.add(key)

    if not nodes.known:
        return FileNodes(relpath, False, "no test functions were found by the AST")
    return nodes


def conftests_for(relpath: str) -> list[str]:
    """Every conftest.py path that pytest would apply to a test file."""
    parts = PurePosixPath(relpath).parts[:-1]
    out = ["conftest.py"]
    for i in range(1, len(parts) + 1):
        out.append("/".join([*parts[:i], "conftest.py"]))
    return out


def narrow_selection(
    root: Path,
    selection: Selection,
    infos: dict[str, ModuleInfo],
) -> dict[str, FileNodes]:
    """Apply node narrowing to every file in a file-level selection.

    Files selected for a reason the analysis cannot refine (the test file
    itself changed, always_run, a changed conftest subtree) keep all of their
    tests, as do files sitting under a conftest that is itself affected: its
    fixtures can apply to any test there without being named in the file.
    """
    out: dict[str, FileNodes] = {}
    if selection.select_all:
        for test in selection.tests:
            out[test.relpath] = FileNodes(test.relpath, False, "everything is selected")
        return out

    for test in selection.tests:
        rel = test.relpath
        if test.distance == 0:
            out[rel] = FileNodes(rel, False, "the test file itself changed")
            continue
        if test.distance is None:
            out[rel] = FileNodes(rel, False, test.reason)
            continue
        hit = next((c for c in conftests_for(rel) if c in selection.affected_files), None)
        if hit is not None:
            out[rel] = FileNodes(rel, False, f"{hit} is affected and its fixtures apply here")
            continue
        module = infos[rel].module if rel in infos else rel
        out[rel] = narrow_file(root, rel, selection.affected_modules, module)
    return out
