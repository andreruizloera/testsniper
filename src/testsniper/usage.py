"""Name-usage primitives shared by the in-file and cross-file analyses.

Both `nodes.py` (which test functions in a file reach the change) and
`fixtures.py` (which conftest fixtures reach it) ask the same question of a
Python file: which names does this piece of syntax read, and do any of them
trace back to an import of something affected. This module is that question,
with no opinion about tests, fixtures, git, or pytest.

Nothing here does I/O. Callers pass in a parsed tree and get back names.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from testsniper.scanner import resolve_from

# Dotted module name -> the symbols in it a change reaches. A module that is
# affected but absent from such a map has ALL of its symbols affected, which
# is what every caller here meant before a changed module's own diff could be
# read. ``symbols.py`` produces these; nothing in this module produces one.
SymbolMap = Mapping[str, frozenset[str]]

# Pseudo-name recorded when a function imports an affected module locally. It
# is seeded into the affected-name set, so a function-local import selects its
# own function through the ordinary name-usage path and nothing else.
LOCAL_IMPORT = "\x00local-import"

# Builtins that make name usage unreadable. getattr is excluded on purpose: it
# is far too common in ordinary test code to carry any signal.
_OPAQUE_BUILTINS: frozenset[str] = frozenset({"globals", "locals", "eval", "exec"})

# Attribute calls that reach a fixture through a string instead of through a
# parameter name. The AST can see the call and not the connection.
_OPAQUE_CALLS: frozenset[str] = frozenset({"getfixturevalue"})

# Statements that define a name, compared one by one rather than as part of
# the module-level code that runs on import.
DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


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


def affected_parent(
    dotted: str, affected: set[str], symbols: SymbolMap | None = None, inside: str = ""
) -> str | None:
    """An affected package whose IMPORT SIDE EFFECT ``dotted`` cannot be narrowed past.

    ``import a.b`` and ``from a.b import c`` both run ``a/__init__.py`` before
    anything in ``a.b``. Only STRICT prefixes count: ``dotted`` itself being
    affected is the ordinary case every caller already handles.

    A parent that appears in ``symbols`` is NOT returned, and that exclusion is
    what keeps this from swallowing the common layout where a package
    ``__init__`` re-exports from its submodules. Being in that map is exactly
    the guarantee needed: both producers of it refuse when module-level code
    changed, reads something affected, or cannot be read, so a package with a
    usable symbol set has module-level code that is known inert, and running it
    on the way to a submodule changes nothing. A parent absent from the map is
    one whose import can do anything, and there is no name to track it by.

    ``inside`` is the package the importing file itself sits in. A package
    the importer is already part of is not a side effect of the import: by the
    time ``pkg/__init__.py`` runs ``from pkg.changed import build``, ``pkg`` is
    already executing, and by the time ``pkg/other.py`` runs at all its
    ``__init__`` has run. Without this, a package whose ``__init__`` re-exports
    from its own submodule would refuse to narrow itself. Nothing is lost:
    every import that crosses INTO the package from outside is checked by this
    same rule, where the side effect really is one.
    """
    parts = dotted.split(".")
    for i in range(1, len(parts)):
        prefix = ".".join(parts[:i])
        if inside == prefix or inside.startswith(f"{prefix}."):
            continue
        if prefix in affected and (symbols is None or prefix not in symbols):
            return prefix
    return None


def from_import_is_affected(
    module: str,
    name: str,
    affected: set[str],
    symbols: SymbolMap | None = None,
) -> bool:
    """Whether ``from <module> import <name>`` binds something affected.

    The module must be affected *exactly*, not merely be a package that
    contains an affected submodule: ``from pkg import other`` does not reach
    ``pkg.changed``. What does reach it is the submodule itself
    (``from pkg import changed``), or a package whose own ``__init__`` is in
    the closure because it re-exports from the change.

    ``symbols`` narrows the first of those. When it names ``module``, the
    change was localized to that module's own symbols, so this import binds
    something affected only if ``name`` is one of them. A module absent from
    the map keeps the older answer, which is that all of its symbols are
    affected. The submodule reading is unaffected either way: ``pkg.changed``
    is a module, not a symbol of ``pkg``.
    """
    if module in affected:
        if symbols is None or module not in symbols:
            return True
        if name in symbols[module]:
            return True
    return is_affected(f"{module}.{name}", affected)


def qualify(names: set[str], prefix: str) -> set[str]:
    """Scope ``self.x`` pseudo-names to the class path they were read in."""
    if not prefix:
        return set(names)
    return {f"{prefix}{n}" if n.startswith("self.") else n for n in names}


def package_parts(relpath: str, module: str) -> list[str]:
    """The dotted package a file sits in, for resolving relative imports."""
    parts = module.split(".")
    if PurePosixPath(relpath).name == "__init__.py":
        return parts
    return parts[:-1]


class Usage:
    """The names a syntax tree reads, plus the flag that stops narrowing."""

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.opaque = False
        self.opaque_why = ""

    def mark_opaque(self, why: str) -> None:
        self.opaque = True
        if not self.opaque_why:
            self.opaque_why = why

    def merge(self, other: Usage) -> None:
        self.names |= other.names
        if other.opaque:
            self.mark_opaque(other.opaque_why)


def _string_args(call: ast.Call) -> list[str]:
    return [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]


def collect_usage(
    node: ast.AST,
    pkg_parts: list[str],
    affected: set[str],
    symbols: SymbolMap | None = None,
) -> Usage:
    """Every name read anywhere inside a syntax tree.

    Parameters count as names, so a fixture is reached from the test that
    requests it, whether the fixture is defined in the same file or in a
    conftest. ``self.method`` is recorded as a pseudo-name so sibling methods
    resolve later, and ``pytest.mark.usefixtures("x")`` contributes ``x``,
    since that mark requests a fixture the parameter list never mentions. A
    local import of an affected module contributes LOCAL_IMPORT.
    """
    usage = Usage()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            usage.names.add(child.id)
            if child.id in _OPAQUE_BUILTINS:
                usage.mark_opaque("globals/eval/exec")
        elif isinstance(child, ast.arg):
            usage.names.add(child.arg)
        elif isinstance(child, ast.Attribute):
            if isinstance(child.value, ast.Name) and child.value.id == "self":
                usage.names.add(f"self.{child.attr}")
        elif isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                if func.attr == "usefixtures":
                    usage.names.update(_string_args(child))
                elif func.attr in _OPAQUE_CALLS:
                    usage.mark_opaque(f"request.{func.attr}")
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
                elif from_import_is_affected(resolved, alias.name, affected, symbols):
                    usage.names.add(LOCAL_IMPORT)
    return usage


def module_bindings(
    tree: ast.Module,
    pkg_parts: list[str],
    affected: set[str],
    symbols: SymbolMap | None = None,
) -> tuple[set[str], str | None]:
    """Module-level import bindings whose target is affected.

    Returns the bound names, and a blocking reason when an import cannot be
    attributed to individual names precisely enough to narrow on. The reason
    carries a ``{where}`` placeholder so the caller can name the file the way
    its own output reads.

    ``symbols`` refines only the from-import case, where the bound name IS the
    symbol. A plain ``import pkg.changed`` binds the module object, and every
    attribute read off it is an ``ast.Attribute`` this analysis does not track
    back to a name, so which symbol a user of that binding touches is not
    knowable here and the whole module stays affected.

    An import whose PARENT package is affected is a block rather than a
    binding. ``from a.b import c`` executes ``a/__init__.py`` and then binds
    only ``c``, and ``a``'s own symbols are not reachable through ``c``, so
    there is no name for usage tracking to follow and no honest way to narrow.
    ``import a.b`` is different and stays a binding: it binds ``a`` itself, so
    every read of ``a.anything`` is a read of a name in this set.
    """
    inside = ".".join(pkg_parts)
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    if is_affected(alias.name, affected):
                        bound.add(alias.asname)
                    else:
                        parent = affected_parent(alias.name, affected, symbols, inside)
                        if parent is not None:
                            return bound, (
                                f"{{where}} imports {alias.name} as {alias.asname},"
                                f" and its package {parent} is affected and runs on import"
                            )
                elif is_affected(alias.name, affected, with_prefixes=True):
                    bound.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            resolved, unresolved = resolve_from(node, pkg_parts)
            if unresolved:
                return bound, "a relative import in {where} could not be resolved"
            if resolved is None:
                continue
            parent = affected_parent(resolved, affected, symbols, inside)
            if parent is not None:
                return bound, (
                    f"{{where}} imports from {resolved},"
                    f" and its package {parent} is affected and runs on import"
                )
            for alias in node.names:
                if alias.name == "*":
                    if resolved in affected:
                        return bound, f"star import from affected module {resolved} in {{where}}"
                    continue
                if from_import_is_affected(resolved, alias.name, affected, symbols):
                    bound.add(alias.asname or alias.name)
    return bound, None


def has_dynamic_import(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "__import__":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            return True
    return False


def declares_pytest_plugins(tree: ast.Module) -> bool:
    """Whether the module declares ``pytest_plugins``.

    A declared plugin can register fixtures from a module this analysis never
    reads, so the names visible to a test stop being knowable from source.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in node.targets):
                return True
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "pytest_plugins"
        ):
            return True
    return False


def module_statements(tree: ast.Module) -> list[str]:
    """Module-level statements that run on import, as parsed syntax.

    Definitions and imports are left out because they are compared one at a
    time and more precisely. Docstrings are NOT exempt, here or in a
    definition: under ``--doctest-modules`` pytest collects doctests out of a
    module, so a docstring can be a test and editing it can change a result.
    """
    return [
        ast.dump(stmt)
        for stmt in tree.body
        if not isinstance(stmt, (*DEF_TYPES, ast.Import, ast.ImportFrom))
    ]


def bound_names(stmt: ast.Import | ast.ImportFrom) -> set[str]:
    """The module-level names an import statement binds."""
    return {alias.asname or alias.name.split(".")[0] for alias in stmt.names}


def changed_imports(old: ast.Module, new: ast.Module) -> tuple[set[str], bool]:
    """Names bound by a module-level import statement the diff touched.

    The second value says a star import moved, which makes the names it binds
    unknowable, so callers refuse rather than narrow.
    """
    old_imports = [s for s in old.body if isinstance(s, ast.Import | ast.ImportFrom)]
    new_imports = [s for s in new.body if isinstance(s, ast.Import | ast.ImportFrom)]
    shared = {ast.dump(s) for s in old_imports} & {ast.dump(s) for s in new_imports}
    names: set[str] = set()
    for stmt in (*old_imports, *new_imports):
        if ast.dump(stmt) in shared:
            continue
        if any(alias.name == "*" for alias in stmt.names):
            return names, True
        names |= bound_names(stmt)
    return names, False


def reaches(start: set[str], defs: dict[str, set[str]], affected_names: set[str]) -> bool:
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


FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class FixtureInfo:
    """A pytest fixture as its decorator declares it."""

    # The name tests request. ``@pytest.fixture(name="cart")`` renames it, so
    # this is not always the function name.
    name: str
    func: str
    autouse: bool


def fixture_info(node: FuncDef) -> FixtureInfo | None:
    """Read a function's decorators as a fixture declaration, or None.

    Matches any decorator whose final attribute is ``fixture``, so
    ``@pytest.fixture``, ``@fixture``, and third-party spellings such as
    ``@pytest_asyncio.fixture`` are all recognized. An ``autouse`` value that
    is not a literal counts as autouse: the safe reading of an unreadable one.
    """
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call is not None else decorator
        if isinstance(target, ast.Attribute):
            matched = target.attr == "fixture"
        elif isinstance(target, ast.Name):
            matched = target.id == "fixture"
        else:
            matched = False
        if not matched:
            continue
        name = node.name
        autouse = False
        for keyword in call.keywords if call is not None else []:
            if keyword.arg == "name":
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    name = keyword.value.value
            elif keyword.arg == "autouse":
                autouse = not (
                    isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                )
        return FixtureInfo(name=name, func=node.name, autouse=autouse)
    return None


@dataclass
class ModuleIndex:
    """What one module defines and what those definitions read."""

    # Name defined in this module -> the names its body reads. A method is
    # keyed by its class path as ``Outer::self.method``.
    defs: dict[str, set[str]] = field(default_factory=dict)
    # Names read by module-level code, which runs on import.
    module_usage: Usage = field(default_factory=Usage)
    # Class path prefix ("Outer::") -> names shared by every method on it.
    class_shared: dict[str, Usage] = field(default_factory=dict)
    # Module-level function definitions, in source order.
    functions: list[FuncDef] = field(default_factory=list)
    # Class path prefix -> the methods defined directly on that class.
    methods: dict[str, list[FuncDef]] = field(default_factory=dict)


def index_module(
    tree: ast.Module,
    pkg_parts: list[str],
    affected: set[str],
    symbols: SymbolMap | None = None,
) -> ModuleIndex:
    """Index a module's definitions, so name usage can propagate through them."""
    index = ModuleIndex()

    def record_class(node: ast.ClassDef, prefix: str) -> Usage:
        """Index one class's methods and return the names its body reads."""
        shared = Usage()
        method_names: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, FuncDef):
                stmt_usage = collect_usage(stmt, pkg_parts, affected, symbols)
                method_names.append(stmt.name)
                index.methods.setdefault(prefix, []).append(stmt)
                index.defs.setdefault(f"{prefix}self.{stmt.name}", set()).update(
                    qualify(stmt_usage.names, prefix)
                )
                if stmt_usage.opaque:
                    shared.mark_opaque(stmt_usage.opaque_why)
            elif isinstance(stmt, ast.ClassDef):
                shared.merge(record_class(stmt, f"{prefix}{stmt.name}::"))
            elif not isinstance(stmt, ast.Import | ast.ImportFrom):
                shared.merge(collect_usage(stmt, pkg_parts, affected, symbols))
        for decorator in node.decorator_list:
            shared.merge(collect_usage(decorator, pkg_parts, affected, symbols))
        # Class-body state is shared by every method defined on the class.
        for name in method_names:
            index.defs.setdefault(f"{prefix}self.{name}", set()).update(
                qualify(shared.names, prefix)
            )
        index.class_shared[prefix] = shared
        return shared

    outer_shared: list[Usage] = []
    for stmt in tree.body:
        if isinstance(stmt, FuncDef):
            usage = collect_usage(stmt, pkg_parts, affected, symbols)
            index.functions.append(stmt)
            index.defs.setdefault(stmt.name, set()).update(usage.names)
            if usage.opaque:
                index.module_usage.mark_opaque(usage.opaque_why)
        elif isinstance(stmt, ast.ClassDef):
            outer_shared.append(record_class(stmt, f"{stmt.name}::"))
        elif not isinstance(stmt, ast.Import | ast.ImportFrom):
            index.module_usage.merge(collect_usage(stmt, pkg_parts, affected, symbols))

    for shared in outer_shared:
        if shared.opaque:
            index.module_usage.mark_opaque(shared.opaque_why)
    return index
