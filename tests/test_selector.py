"""Tests for selection across modes, triggers, and confidence scoring."""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.config import load_config
from testsniper.selector import Selection, select


def _run(root: Path, changed: list[str], mode: str = "default") -> Selection:
    return select(root, changed, mode, load_config(root))  # type: ignore[arg-type]


def _paths(sel: Selection) -> list[str]:
    return [t.relpath for t in sel.tests]


def test_default_full_transitive_closure(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/core.py"])
    assert _paths(sel) == [
        "tests/test_core.py",
        "tests/test_mid.py",
        "tests/test_top.py",
        "tests/smoke/test_smoke.py",
    ]
    assert sel.selected_tests == 4
    assert sel.total_tests == 4


def test_ranking_by_distance(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/core.py"])
    by_path = {t.relpath: t.distance for t in sel.tests}
    assert by_path["tests/test_core.py"] == 1
    assert by_path["tests/test_mid.py"] == 2
    assert by_path["tests/test_top.py"] == 3
    assert by_path["tests/smoke/test_smoke.py"] is None


def test_aggressive_selects_direct_importers_only(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/core.py"], mode="aggressive")
    assert _paths(sel) == ["tests/test_core.py", "tests/smoke/test_smoke.py"]
    assert sel.confidence == "Medium"
    assert any("transitive" in r for r in sel.confidence_reasons)


def test_default_mid_change_excludes_upstream_test(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/top.py"])
    assert "tests/test_core.py" not in _paths(sel)
    assert "tests/test_top.py" in _paths(sel)


def test_always_run_merged_even_when_unrelated(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/top.py"])
    assert "tests/smoke/test_smoke.py" in _paths(sel)
    smoke = next(t for t in sel.tests if t.relpath == "tests/smoke/test_smoke.py")
    assert smoke.distance is None
    assert "always_run" in smoke.reason


def test_changed_test_file_selects_itself(sample_project: Path) -> None:
    sel = _run(sample_project, ["tests/test_mid.py"])
    picked = next(t for t in sel.tests if t.relpath == "tests/test_mid.py")
    assert picked.distance == 0


def test_safe_widens_to_package(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/top.py"], mode="safe")
    assert "tests/test_core.py" in _paths(sel)
    assert any("widened" in n for n in sel.notes)


def test_safe_config_change_selects_everything(sample_project: Path) -> None:
    sel = _run(sample_project, ["pyproject.toml"], mode="safe")
    assert sel.select_all
    assert sel.selected_tests == sel.total_tests
    assert sel.select_all_reason is not None


def test_safe_non_python_change_selects_everything(sample_project: Path) -> None:
    write_tree(sample_project, {"data/config.json": "{}\n"})
    sel = _run(sample_project, ["data/config.json"], mode="safe")
    assert sel.select_all


def test_default_config_change_degrades_to_low(sample_project: Path) -> None:
    sel = _run(sample_project, ["pyproject.toml", "pkg/core.py"])
    assert not sel.select_all
    assert sel.confidence == "Low"
    assert any("--safe" in r for r in sel.confidence_reasons)


def test_changed_conftest_selects_subtree_in_default(sample_project: Path) -> None:
    write_tree(sample_project, {"tests/conftest.py": "import pytest\n"})
    sel = _run(sample_project, ["tests/conftest.py"])
    assert set(_paths(sel)) == {
        "tests/test_core.py",
        "tests/test_mid.py",
        "tests/test_top.py",
        "tests/smoke/test_smoke.py",
    }


def test_changed_conftest_ignored_in_aggressive_with_low_confidence(
    sample_project: Path,
) -> None:
    write_tree(sample_project, {"tests/conftest.py": "import pytest\n"})
    sel = _run(sample_project, ["tests/conftest.py"], mode="aggressive")
    assert sel.confidence == "Low"


def test_unreached_changed_module_reported(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/lonely.py"])
    assert sel.unreached == ["pkg/lonely.py"]
    assert sel.confidence == "Medium"
    assert any("no test imports" in r for r in sel.confidence_reasons)


def test_deleted_module_selects_its_importers(sample_project: Path) -> None:
    write_tree(
        sample_project,
        {"tests/test_gone.py": "from pkg.gone import thing\n\ndef test_gone(): pass\n"},
    )
    sel = _run(sample_project, ["pkg/gone.py"])
    assert "tests/test_gone.py" in _paths(sel)
    assert any("deleted" in n for n in sel.notes)


def test_star_import_degrades_confidence(sample_project: Path) -> None:
    write_tree(sample_project, {"pkg/wild.py": "from pkg.core import *\n"})
    sel = _run(sample_project, ["pkg/core.py"])
    assert sel.confidence == "Medium"
    assert any("star import" in r for r in sel.confidence_reasons)


def test_dynamic_import_degrades_confidence(sample_project: Path) -> None:
    write_tree(
        sample_project,
        {"pkg/dyn.py": "import importlib\nm = importlib.import_module('pkg.core')\n"},
    )
    sel = _run(sample_project, ["pkg/core.py"])
    assert sel.confidence == "Medium"
    assert any("dynamic import" in r for r in sel.confidence_reasons)


def test_parse_error_degrades_to_low(sample_project: Path) -> None:
    write_tree(sample_project, {"pkg/broken.py": "def nope(:\n"})
    sel = _run(sample_project, ["pkg/core.py"])
    assert sel.confidence == "Low"


def test_clean_selection_is_high_confidence(sample_project: Path) -> None:
    sel = _run(sample_project, ["pkg/core.py"])
    assert sel.confidence == "High"
    assert sel.confidence_reasons == []


def test_no_changes_selects_nothing(sample_project: Path) -> None:
    sel = _run(sample_project, [])
    assert sel.tests == []
    assert sel.total_tests == 4
