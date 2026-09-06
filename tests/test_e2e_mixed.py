"""End-to-end node-level runs against the committed mixed example project.

The mixed project exists because the generated fixture project cannot show
this: there, every test in a file uses the same module, so narrowing has
nothing to remove. Here a change to store/pricing.py reaches seven of the
thirteen test functions in tests/test_checkout.py and none of the other file.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import git, git_repo

MIXED = Path(__file__).resolve().parent.parent / "examples" / "mixed_project"


@pytest.fixture
def mixed_repo(tmp_path: Path) -> Path:
    dest = tmp_path / "proj"
    shutil.copytree(MIXED, dest)
    git_repo(dest)
    return dest


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "testsniper", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _pytest(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _change_pricing(repo: Path) -> None:
    pricing = repo / "store" / "pricing.py"
    pricing.write_text(
        pricing.read_text()
        + "\n\ndef bulk_discount(cents: int) -> int:\n    return cents * 9 // 10\n"
    )


def test_file_level_run_cannot_narrow_inside_the_file(mixed_repo: Path) -> None:
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Selected: tests/test_checkout.py" in proc.stdout
    assert "Running 13 of 16 tests..." in proc.stdout
    assert "14 passed" in proc.stdout


def test_nodes_run_drops_the_tests_that_do_not_use_pricing(mixed_repo: Path) -> None:
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "Running 7 of 16 tests (6 more dropped inside the selected files)..." in out
    assert "8 passed, 6 deselected" in out
    assert "Skipped: 9 (3 in unselected files, 6 deselected inside selected files)" in out
    assert "Selection confidence: High" in out


def test_nodes_list_names_the_selected_functions(mixed_repo: Path) -> None:
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "would run 7 of 16 tests" in out
    assert "7 of 13 tests: narrowed by name usage" in out
    # Reached directly, and through the taxed_total fixture respectively.
    assert "test_price_with_tax_rounds_half_up" in out
    assert "test_receipt_shows_the_taxed_total" in out
    # Never selected: these touch shipping and receipt formatting only.
    assert "test_shipping_is_flat_under_a_kilo" not in out
    assert "test_amounts_are_dollars_and_cents" not in out


def test_plugin_narrows_a_plain_pytest_invocation(mixed_repo: Path) -> None:
    _change_pricing(mixed_repo)
    proc = _pytest(mixed_repo, "--testsniper")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "testsniper: default mode, working tree vs HEAD" in out
    assert "selected 8 of 20 collected tests" in out
    assert "tests/test_checkout.py: 8 of 14, narrowed by name usage" in out
    assert "8 passed, 12 deselected" in out


def test_changing_shipping_selects_a_different_slice(mixed_repo: Path) -> None:
    shipping = mixed_repo / "store" / "shipping.py"
    shipping.write_text(shipping.read_text() + "\nEXPRESS_CENTS = 1999\n")
    proc = _pytest(mixed_repo, "--testsniper")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    # Both files import shipping; only the tests that use it survive.
    assert "tests/test_checkout.py: 2 of 14" in out
    assert "tests/test_shipping_rules.py: 6 of 6" not in out
    assert "8 passed, 12 deselected" in out


def test_changing_the_test_file_itself_runs_all_of_it(mixed_repo: Path) -> None:
    checkout = mixed_repo / "tests" / "test_checkout.py"
    checkout.write_text(checkout.read_text() + "\n\ndef test_added():\n    assert True\n")
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all tests: the test file itself changed" in proc.stdout


def test_an_affected_conftest_stops_narrowing_in_its_subtree(mixed_repo: Path) -> None:
    """A conftest that imports the change can inject it into any test there."""
    (mixed_repo / "tests" / "conftest.py").write_text(
        "import pytest\n"
        "\n"
        "from store.pricing import TAX_RATE\n"
        "\n"
        "@pytest.fixture(autouse=True)\n"
        "def _rate():\n"
        "    return TAX_RATE\n"
    )
    git(mixed_repo, "add", "-A")
    git(mixed_repo, "commit", "-q", "-m", "add conftest")
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all tests: tests/conftest.py is affected and its fixtures apply here" in proc.stdout
