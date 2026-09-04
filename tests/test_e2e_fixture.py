"""End-to-end run against the committed fixture project, using real pytest."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import git_repo

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "fixture_project"


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    dest = tmp_path / "proj"
    shutil.copytree(FIXTURE, dest)
    git_repo(dest)
    return dest


def _sniper(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "testsniper", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_end_to_end_default_run(fixture_repo: Path) -> None:
    layer1 = fixture_repo / "fixture_lib" / "c4" / "layer1.py"
    layer1.write_text(layer1.read_text() + "\n\ndef extra() -> int:\n    return 42\n")

    proc = _sniper(fixture_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "Changed: fixture_lib/c4/layer1.py" in out
    assert (
        "Selected: tests/test_c4_layer1.py, tests/test_c4_layer2.py,"
        " tests/test_c4_api.py, tests/smoke/test_smoke.py" in out
    )
    assert "Running 32 of 402 tests..." in out
    assert "32 passed" in out
    assert "Skipped: 370 (not selected)" in out
    assert "Selection confidence: High" in out


def test_end_to_end_aggressive_run(fixture_repo: Path) -> None:
    layer1 = fixture_repo / "fixture_lib" / "c4" / "layer1.py"
    layer1.write_text(layer1.read_text() + "\nEXTRA = 1\n")

    proc = _sniper(fixture_repo, "--aggressive")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Running 12 of 402 tests..." in proc.stdout
    assert "12 passed" in proc.stdout
    assert "Selection confidence: Medium" in proc.stdout


def test_end_to_end_safe_list(fixture_repo: Path) -> None:
    layer1 = fixture_repo / "fixture_lib" / "c4" / "layer1.py"
    layer1.write_text(layer1.read_text() + "\nEXTRA = 1\n")

    proc = _sniper(fixture_repo, "--safe", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "would run 42 of 402 tests" in out
    assert "tests/test_c4_base.py" in out


def test_end_to_end_broken_change_fails(fixture_repo: Path) -> None:
    base = fixture_repo / "fixture_lib" / "c4" / "base.py"
    base.write_text("def base_value() -> int:\n    return -1\n")

    proc = _sniper(fixture_repo)
    assert proc.returncode != 0
    assert "Running 42 of 402 tests..." in proc.stdout
