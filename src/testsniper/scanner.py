"""Repository-wide AST import scanning.

Walks every Python file in the repository, records what each file imports
(absolute imports, from-imports, and package-relative imports), and flags
constructs that static analysis cannot fully trace: star imports, dynamic
imports (importlib.import_module / __import__), and files that fail to parse.

It also records one dependency that is not an import at all: a
``python -m pkg`` subprocess, which is how a test exercises a command
line rather than a function. See ``entrypoints.py`` for what that reads
and, more importantly, what it refuses to read.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from testsniper.entrypoints import subprocess_modules

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".eggs",
        "build",
        "dist",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "site-packages",
    }
)


@dataclass
class ModuleInfo:
    """Static import facts about one Python file."""

    relpath: str
    module: str
    deps: set[str] = field(default_factory=set)
    candidates: set[str] = field(default_factory=set)
    star_imports: set[str] = field(default_factory=set)
    subprocess_modules: set[str] = field(default_factory=set)
    dynamic_import: bool = False
    parse_error: bool = False
    unresolved_relative: bool = False

    def all_referenced(self) -> set[str]:
        """Every dotted name this file might depend on."""
        return self.deps | self.star_imports | self.candidates


def module_name(root: Path, relpath: Path | str) -> str:
    """Compute the dotted module name a file is importable as.

    Walks upward from the file while ``__init__.py`` exists, so both flat
    and src/ layouts resolve naturally (the src directory itself has no
    ``__init__.py`` and stops the walk).
    """
    rel = Path(relpath)
    pkg_parts: list[str] = []
    cur = rel.parent
    while cur != Path(".") and (root / cur / "__init__.py").is_file():
        pkg_parts.insert(0, cur.name)
        cur = cur.parent
    if rel.stem == "__init__":
        if pkg_parts:
            return ".".join(pkg_parts)
        return rel.stem
    return ".".join([*pkg_parts, rel.stem])


def _expand_prefixes(dotted: str) -> set[str]:
    """``a.b.c`` also executes packages ``a`` and ``a.b``, so record all."""
    parts = dotted.split(".")
    return {".".join(parts[:i]) for i in range(1, len(parts) + 1)}


def parse_module(root: Path, relpath: Path) -> ModuleInfo:
    """Parse one file and extract its import facts."""
    info = ModuleInfo(relpath=str(PurePosixPath(relpath)), module=module_name(root, relpath))
    try:
        source = (root / relpath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(relpath))
    except (SyntaxError, ValueError, OSError):
        info.parse_error = True
        return info

    mod_parts = info.module.split(".")
    is_package = relpath.name == "__init__.py"
    pkg_parts = mod_parts if is_package else mod_parts[:-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                info.deps |= _expand_prefixes(alias.name)
        elif isinstance(node, ast.ImportFrom):
            full, unresolved = resolve_from(node, pkg_parts)
            if unresolved:
                info.unresolved_relative = True
            if full is None:
                continue
            info.deps |= _expand_prefixes(full)
            for alias in node.names:
                if alias.name == "*":
                    info.star_imports.add(full)
                else:
                    info.candidates.add(f"{full}.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            is_dunder = isinstance(func, ast.Name) and func.id == "__import__"
            is_importlib = isinstance(func, ast.Attribute) and func.attr == "import_module"
            if is_dunder or is_importlib:
                info.dynamic_import = True
            # A `python -m pkg` subprocess is a dependency the import
            # statements do not record. It is folded into deps so the
            # reverse graph treats it as the edge it is.
            for target in subprocess_modules(node):
                info.subprocess_modules.add(target)
                info.deps |= _expand_prefixes(target)
    return info


def resolve_from(node: ast.ImportFrom, pkg_parts: list[str]) -> tuple[str | None, bool]:
    """Resolve a from-import to a dotted name, handling relative levels.

    Returns the dotted name and whether resolution failed. A relative import
    that climbs past the package root, or one whose target resolves to
    nothing, is unresolved: the caller should treat it as a blind spot rather
    than as an absent dependency.
    """
    if node.level == 0:
        return node.module, False
    drop = node.level - 1
    if drop > len(pkg_parts):
        return None, True
    base = pkg_parts[: len(pkg_parts) - drop]
    target = [*base, *(node.module.split(".") if node.module else [])]
    if not target:
        return None, True
    return ".".join(target), False


def scan_repo(root: Path) -> dict[str, ModuleInfo]:
    """Scan every Python file under root, keyed by POSIX relative path."""
    infos: dict[str, ModuleInfo] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if not path.is_file():
            continue
        info = parse_module(root, rel)
        infos[info.relpath] = info
    return infos
