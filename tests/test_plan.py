"""Tests for the plan: the JSON contract between the CLI and the plugin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import git_repo, write_tree

from testsniper import plan as plan_mod
from testsniper.config import load_config
from testsniper.nodes import FileNodes, narrow_selection
from testsniper.plan import Plan, PlanError
from testsniper.scanner import scan_repo
from testsniper.selector import select


def test_round_trip_preserves_every_field() -> None:
    plan = Plan(
        root="/tmp/repo",
        select_all=False,
        files={
            "tests/test_a.py": FileNodes(
                relpath="tests/test_a.py",
                narrowed=True,
                reason="narrowed by name usage",
                selected={("", "test_one"), ("TestX", "test_two")},
                known={("", "test_one"), ("TestX", "test_two"), ("", "test_three")},
            ),
            "tests/test_b.py": FileNodes("tests/test_b.py", False, "always_run"),
        },
        indexed={"tests/test_a.py", "tests/test_b.py", "tests/test_c.py"},
        confidence="Medium",
        confidence_reasons=["star imports can hide dependencies"],
        summary="1 changed file(s)",
    )
    back = plan_mod.loads(plan_mod.dumps(plan))
    assert back == plan


def test_dumps_is_stable_and_sorted() -> None:
    plan = Plan(root="/tmp/repo", indexed={"b.py", "a.py"})
    data = json.loads(plan_mod.dumps(plan))
    assert data["version"] == plan_mod.PLAN_VERSION
    assert data["indexed"] == ["a.py", "b.py"]


def test_verdict_deselects_files_absent_from_the_plan() -> None:
    plan = Plan(
        root="/tmp/repo", files={"tests/test_a.py": FileNodes("tests/test_a.py", False, "")}
    )
    assert plan.verdict("tests/test_a.py", ("", "test_one"))
    assert not plan.verdict("tests/test_b.py", ("", "test_one"))


def test_verdict_under_select_all_keeps_everything() -> None:
    plan = Plan(root="/tmp/repo", select_all=True)
    assert plan.verdict("anything.py", ("", "test_one"))


def test_unsupported_version_is_rejected() -> None:
    with pytest.raises(PlanError, match="version"):
        plan_mod.loads(json.dumps({"version": 99, "root": "/tmp", "files": {}}))


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(PlanError, match="valid JSON"):
        plan_mod.loads("{not json")


def test_missing_root_is_rejected() -> None:
    with pytest.raises(PlanError, match="root"):
        plan_mod.loads(json.dumps({"version": 1, "files": {}}))


def test_missing_files_map_is_rejected() -> None:
    with pytest.raises(PlanError, match="files map"):
        plan_mod.loads(json.dumps({"version": 1, "root": "/tmp"}))


def test_reading_a_missing_file_is_a_plan_error(tmp_path: Path) -> None:
    with pytest.raises(PlanError, match="could not read"):
        plan_mod.read(tmp_path / "nope.json")


def test_build_plan_from_a_real_selection(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "p"\nversion = "0.1.0"\n',
            "conftest.py": "",
            "pkg/__init__.py": "",
            "pkg/core.py": "def core():\n    return 1\n",
            "pkg/other.py": "def other():\n    return 2\n",
            "tests/test_it.py": (
                "from pkg.core import core\n"
                "from pkg.other import other\n"
                "\n"
                "def test_core():\n"
                "    assert core() == 1\n"
                "\n"
                "def test_other():\n"
                "    assert other() == 2\n"
            ),
        },
    )
    git_repo(tmp_path)
    infos = scan_repo(tmp_path)
    sel = select(tmp_path, ["pkg/core.py"], "default", load_config(tmp_path), infos)
    nodes = narrow_selection(tmp_path, sel, infos)
    plan = plan_mod.build_plan(tmp_path, sel, nodes, summary="one file")

    assert plan.root == str(tmp_path.resolve())
    assert plan.indexed == {"tests/test_it.py"}
    assert plan.summary == "one file"
    assert plan.verdict("tests/test_it.py", ("", "test_core"))
    assert not plan.verdict("tests/test_it.py", ("", "test_other"))
    # And it survives a trip through JSON unchanged.
    assert plan_mod.loads(plan_mod.dumps(plan)) == plan
