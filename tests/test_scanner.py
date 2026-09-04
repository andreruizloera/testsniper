"""Tests for AST import scanning and module name resolution."""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.scanner import module_name, parse_module, scan_repo


def test_module_name_flat_package(tmp_path: Path) -> None:
    write_tree(tmp_path, {"pkg/__init__.py": "", "pkg/sub/__init__.py": "", "pkg/sub/mod.py": ""})
    assert module_name(tmp_path, Path("pkg/sub/mod.py")) == "pkg.sub.mod"
    assert module_name(tmp_path, Path("pkg/sub/__init__.py")) == "pkg.sub"
    assert module_name(tmp_path, Path("pkg/__init__.py")) == "pkg"


def test_module_name_src_layout(tmp_path: Path) -> None:
    write_tree(tmp_path, {"src/pkg/__init__.py": "", "src/pkg/mod.py": ""})
    assert module_name(tmp_path, Path("src/pkg/mod.py")) == "pkg.mod"


def test_module_name_top_level_script(tmp_path: Path) -> None:
    write_tree(tmp_path, {"script.py": ""})
    assert module_name(tmp_path, Path("script.py")) == "script"


def test_plain_import_records_prefixes(tmp_path: Path) -> None:
    write_tree(tmp_path, {"m.py": "import a.b.c\n"})
    info = parse_module(tmp_path, Path("m.py"))
    assert {"a", "a.b", "a.b.c"} <= info.deps


def test_from_import_records_base_and_candidate(tmp_path: Path) -> None:
    write_tree(tmp_path, {"m.py": "from a.b import thing\n"})
    info = parse_module(tmp_path, Path("m.py"))
    assert "a.b" in info.deps
    assert "a.b.thing" in info.candidates


def test_relative_import_resolution(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/sub/__init__.py": "",
            "pkg/sub/mod.py": "from . import sibling\nfrom ..other import name\n",
        },
    )
    info = parse_module(tmp_path, Path("pkg/sub/mod.py"))
    assert "pkg.sub" in info.deps
    assert "pkg.sub.sibling" in info.candidates
    assert "pkg.other" in info.deps
    assert "pkg.other.name" in info.candidates


def test_relative_import_from_package_init(tmp_path: Path) -> None:
    write_tree(tmp_path, {"pkg/__init__.py": "from . import mod\n", "pkg/mod.py": ""})
    info = parse_module(tmp_path, Path("pkg/__init__.py"))
    assert "pkg" in info.deps
    assert "pkg.mod" in info.candidates


def test_relative_import_beyond_top_is_flagged(tmp_path: Path) -> None:
    write_tree(tmp_path, {"pkg/__init__.py": "", "pkg/mod.py": "from ...far import x\n"})
    info = parse_module(tmp_path, Path("pkg/mod.py"))
    assert info.unresolved_relative


def test_star_import_flagged(tmp_path: Path) -> None:
    write_tree(tmp_path, {"m.py": "from a.b import *\n"})
    info = parse_module(tmp_path, Path("m.py"))
    assert "a.b" in info.star_imports


def test_dynamic_import_flagged(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "m1.py": "import importlib\nmod = importlib.import_module('x')\n",
            "m2.py": "mod = __import__('x')\n",
            "m3.py": "import os\n",
        },
    )
    assert parse_module(tmp_path, Path("m1.py")).dynamic_import
    assert parse_module(tmp_path, Path("m2.py")).dynamic_import
    assert not parse_module(tmp_path, Path("m3.py")).dynamic_import


def test_syntax_error_flagged(tmp_path: Path) -> None:
    write_tree(tmp_path, {"bad.py": "def broken(:\n"})
    info = parse_module(tmp_path, Path("bad.py"))
    assert info.parse_error


def test_scan_repo_skips_junk_dirs(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            ".venv/lib/junk.py": "import secret\n",
            "__pycache__/cached.py": "",
        },
    )
    infos = scan_repo(tmp_path)
    assert "pkg/__init__.py" in infos
    assert all(".venv" not in rel and "__pycache__" not in rel for rel in infos)
