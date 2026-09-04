"""Test file indexing following pytest naming conventions."""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

from testsniper.config import Config
from testsniper.scanner import ModuleInfo


def is_test_file(relpath: str) -> bool:
    """pytest default convention: test_*.py or *_test.py."""
    name = PurePosixPath(relpath).name
    if not name.endswith(".py"):
        return False
    return name.startswith("test_") or name.removesuffix(".py").endswith("_test")


def path_is_under(relpath: str, prefix: str) -> bool:
    """True if relpath equals prefix or sits inside it."""
    if not prefix or prefix == ".":
        return True
    rel_parts = PurePosixPath(relpath).parts
    pre_parts = PurePosixPath(prefix).parts
    return rel_parts[: len(pre_parts)] == pre_parts


def test_search_roots(root: Path, config: Config) -> tuple[str, ...]:
    """Where to look for tests: configured testpaths, tests/, or everywhere."""
    if config.testpaths:
        return config.testpaths
    if (root / "tests").is_dir():
        return ("tests",)
    return (".",)


def index_tests(root: Path, infos: dict[str, ModuleInfo], config: Config) -> list[str]:
    """All test files in the scanned repository, sorted."""
    roots = test_search_roots(root, config)
    return sorted(
        rel for rel in infos if is_test_file(rel) and any(path_is_under(rel, r) for r in roots)
    )


def count_tests_in_file(root: Path, relpath: str) -> int:
    """Count test functions in a file the way pytest collects them.

    Counts module-level functions named test_* and test_* methods on
    classes named Test*. Parametrized tests count once, so treat totals
    as function counts rather than exact collected-item counts.
    """
    try:
        tree = ast.parse((root / relpath).read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return 0
    count = 0
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test"):
                count += 1
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and item.name.startswith("test"):
                    count += 1
    return count
