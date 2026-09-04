"""Tests for reverse graph construction and transitive closure."""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.graph import build_reverse_graph, importers_of, reverse_closure
from testsniper.scanner import scan_repo


def _chain_repo(tmp_path: Path) -> dict:
    write_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "",
            "pkg/b.py": "from pkg.a import x\n",
            "pkg/c.py": "import pkg.b\n",
            "tests/test_c.py": "from pkg import c\n",
        },
    )
    return scan_repo(tmp_path)


def test_reverse_edges(tmp_path: Path) -> None:
    infos = _chain_repo(tmp_path)
    reverse = build_reverse_graph(infos)
    assert "pkg/b.py" in reverse["pkg/a.py"]
    assert "pkg/c.py" in reverse["pkg/b.py"]
    assert "tests/test_c.py" in reverse["pkg/c.py"]


def test_importing_submodule_depends_on_package_init(tmp_path: Path) -> None:
    infos = _chain_repo(tmp_path)
    reverse = build_reverse_graph(infos)
    assert "pkg/b.py" in reverse["pkg/__init__.py"]


def test_closure_distances(tmp_path: Path) -> None:
    infos = _chain_repo(tmp_path)
    reverse = build_reverse_graph(infos)
    dist = reverse_closure(reverse, {"pkg/a.py": 0})
    assert dist["pkg/a.py"] == 0
    assert dist["pkg/b.py"] == 1
    assert dist["pkg/c.py"] == 2
    assert dist["tests/test_c.py"] == 3


def test_closure_takes_minimum_distance(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "a.py": "",
            "b.py": "import a\n",
            "c.py": "import a\nimport b\n",
        },
    )
    infos = scan_repo(tmp_path)
    reverse = build_reverse_graph(infos)
    dist = reverse_closure(reverse, {"a.py": 0})
    assert dist["c.py"] == 1


def test_from_import_of_module_resolves_to_it(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "",
            "user.py": "from pkg import mod\n",
        },
    )
    infos = scan_repo(tmp_path)
    reverse = build_reverse_graph(infos)
    assert "user.py" in reverse["pkg/mod.py"]


def test_importers_of_finds_references_for_deleted_modules(tmp_path: Path) -> None:
    write_tree(tmp_path, {"user.py": "from pkg.gone import thing\n"})
    infos = scan_repo(tmp_path)
    assert importers_of(infos, "pkg.gone") == {"user.py"}
