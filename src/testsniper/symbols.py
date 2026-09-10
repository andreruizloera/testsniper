"""Which symbols in a changed module the change can actually reach.

File-level selection asks whether a test file imports a changed MODULE. That
is one unit coarser than the change itself: editing ``price_with_tax`` marks
every importer of ``pricing.core``, including a test file that only ever calls
``line_total``. Node narrowing then keeps every test in that file, because
every name it binds from the changed module counts as affected.

This module reads the changed module's own diff and answers the narrower
question: which of its top-level names can behave differently now. A caller
that knows the answer can treat ``from pricing.core import line_total`` as an
innocent import while ``from pricing.core import price_with_tax`` stays
affected.

Two things make the answer sound rather than merely narrow:

- **Definitions are compared as parsed syntax**, so reflowing a line or
  editing a comment inside a function changes nothing.
- **Usage propagates inside the module.** If ``line_total`` calls
  ``price_with_tax``, then editing ``price_with_tax`` affects ``line_total``
  too, and both names come back.

It is deliberately easy to refuse. Anything the comparison cannot localize
returns a block, and a blocked module keeps the older answer: every symbol in
it is affected. Under-selection is the only failure mode worth preventing
here; running a few extra tests is not.

Nothing here does I/O. Callers pass in source text and get back names.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from testsniper.usage import (
    DEF_TYPES,
    Usage,
    changed_imports,
    collect_usage,
    has_dynamic_import,
    module_statements,
    reaches,
)

__all__ = ["ModuleSymbols", "changed_symbols"]


@dataclass(frozen=True)
class ModuleSymbols:
    """The symbols of one changed module that the change reaches.

    ``block`` is set when the diff could not be localized to individual names,
    in which case ``names`` is meaningless and the caller must fall back to
    treating the whole module as affected.
    """

    names: frozenset[str] = frozenset()
    block: str | None = None

    @property
    def usable(self) -> bool:
        return self.block is None


def _symbol_reads(tree: ast.Module, pkg_parts: list[str]) -> dict[str, set[str]]:
    """Top-level definition name -> every name its own subtree reads.

    A class is one entry covering its bases, decorators, class body and every
    method, because a test that imports the class can reach any of them.
    """
    defs: dict[str, set[str]] = {}
    for stmt in tree.body:
        if isinstance(stmt, DEF_TYPES):
            usage = collect_usage(stmt, pkg_parts, set())
            defs.setdefault(stmt.name, set()).update(usage.names)
    return defs


def _module_usage(tree: ast.Module, pkg_parts: list[str]) -> Usage:
    """Names read by module-level code, which runs on import.

    Definitions and imports are left out: they are compared one at a time and
    more precisely.
    """
    usage = Usage()
    for stmt in tree.body:
        if not isinstance(stmt, (*DEF_TYPES, ast.Import, ast.ImportFrom)):
            usage.merge(collect_usage(stmt, pkg_parts, set()))
    return usage


def _declares_module_getattr(tree: ast.Module) -> bool:
    """Whether the module defines PEP 562 ``__getattr__``.

    A module-level ``__getattr__`` resolves attribute access at runtime, so
    ``from module import name`` can bind something no import statement in the
    file mentions and no comparison of definitions can see.
    """
    return any(isinstance(stmt, DEF_TYPES) and stmt.name == "__getattr__" for stmt in tree.body)


def changed_symbols(
    relpath: str,
    old_source: str | None,
    new_source: str,
    pkg_parts: list[str],
) -> ModuleSymbols:
    """Which top-level names of a changed module the diff can reach.

    ``old_source`` is the module's content at the revision being compared
    against, or None when that revision does not have it.
    """
    if old_source is None:
        return ModuleSymbols(block=f"{relpath} is new; there is no previous content to compare")
    try:
        old = ast.parse(old_source, filename=relpath)
        new = ast.parse(new_source, filename=relpath)
    except (SyntaxError, ValueError):
        return ModuleSymbols(block=f"{relpath} could not be parsed at both revisions")

    if has_dynamic_import(old) or has_dynamic_import(new):
        return ModuleSymbols(block=f"{relpath} imports dynamically")
    if _declares_module_getattr(old) or _declares_module_getattr(new):
        return ModuleSymbols(block=f"{relpath} defines a module-level __getattr__")
    if module_statements(old) != module_statements(new):
        return ModuleSymbols(block=f"module-level code in {relpath} changed; it runs on import")

    seeds, star_moved = changed_imports(old, new)
    if star_moved:
        return ModuleSymbols(block=f"a star import in {relpath} changed")

    old_defs = {s.name: s for s in old.body if isinstance(s, DEF_TYPES)}
    new_defs = {s.name: s for s in new.body if isinstance(s, DEF_TYPES)}
    for name, node in new_defs.items():
        previous = old_defs.get(name)
        if previous is None or ast.dump(previous) != ast.dump(node):
            seeds.add(name)
    # A deleted definition has no node left to compare, and any name that read
    # it now reads something else or nothing.
    seeds.update(name for name in old_defs if name not in new_defs)

    defs = _symbol_reads(new, pkg_parts)
    usage = _module_usage(new, pkg_parts)
    if usage.opaque:
        return ModuleSymbols(block=f"module-level code in {relpath} reads names dynamically")
    if reaches(usage.names, defs, seeds):
        return ModuleSymbols(
            block=f"module-level code in {relpath} reads something the diff changed"
        )

    names = set(seeds)
    names.update(name for name in defs if reaches({name}, defs, seeds))
    return ModuleSymbols(names=frozenset(names))
