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
    """Rewrite price_with_tax, which is the symbol the tests below are about.

    This edits an EXISTING function on purpose. Appending a new one instead
    reaches nothing, because a function nothing calls cannot change what any
    existing test sees; that case has its own test below.
    """
    pricing = repo / "store" / "pricing.py"
    pricing.write_text(
        pricing.read_text().replace(
            "    return int(cents + cents * TAX_RATE + 0.5)",
            "    return int(cents + cents * TAX_RATE + 0.5) if cents else 0",
        )
    )


def _change_receipts(repo: Path) -> None:
    """Rewrite reset_currency, which the autouse fixture in the conftest calls.

    Again an existing function, for the same reason as _change_pricing: the
    autouse fixture reaches this change because it calls THIS symbol.
    """
    receipts = repo / "store" / "receipts.py"
    receipts.write_text(
        receipts.read_text().replace(
            '    _currency["symbol"] = DEFAULT_SYMBOL\n\n\ndef format_cents',
            '    _currency.update({"symbol": DEFAULT_SYMBOL})\n\n\ndef format_cents',
        )
    )


def _append_unused_function(repo: Path) -> None:
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
    assert "Running 16 of 19 tests..." in proc.stdout
    assert "17 passed" in proc.stdout


def test_nodes_run_drops_the_tests_that_do_not_use_pricing(mixed_repo: Path) -> None:
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "Running 7 of 19 tests (9 more dropped inside the selected files)..." in out
    assert "7 passed, 10 deselected" in out
    assert "Skipped: 12 (3 in unselected files, 9 deselected inside selected files)" in out
    assert "Selection confidence: High" in out


def test_nodes_list_names_the_selected_functions(mixed_repo: Path) -> None:
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "would run 7 of 19 tests" in out
    assert "6 of 13 tests: narrowed by name usage and 1 affected conftest fixture" in out
    # Reached directly, and through the taxed_total fixture respectively.
    assert "test_price_with_tax_rounds_half_up" in out
    assert "test_receipt_shows_the_taxed_total" in out
    # Never selected: these touch shipping and receipt formatting only.
    assert "test_shipping_is_flat_under_a_kilo" not in out
    assert "test_amounts_are_dollars_and_cents" not in out


def test_a_test_that_uses_a_different_symbol_is_dropped(mixed_repo: Path) -> None:
    """The one test this feature exists for, on the committed example project.

    tests/test_checkout.py imports both line_total and price_with_tax from
    store/pricing.py. Changing price_with_tax used to run every test in the
    file that reached the module at all, including the parametrized
    test_line_total_multiplies, which cannot see the change: line_total does
    not call price_with_tax.
    """
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "test_price_with_tax_rounds_half_up" in out
    assert "test_line_total_multiplies" not in out


def test_adding_an_unused_function_reaches_no_test(mixed_repo: Path) -> None:
    """A new function nothing calls cannot change what any existing test sees.

    The file-level answer does not move: test_checkout.py still imports the
    changed module and is still selected. What changes is the node-level one,
    and the three tests that survive do so through store/orders.py and the
    conftest fixture, neither of which is the changed module itself.
    """
    _append_unused_function(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "Selected: tests/test_checkout.py" in out
    assert "would run 4 of 19 tests" in out
    assert "3 of 13 tests: narrowed by name usage and 1 affected conftest fixture" in out
    # Every test that reaches pricing only by importing it directly is gone.
    assert "test_price_with_tax_rounds_half_up" not in out
    assert "test_line_total_multiplies" not in out


def test_plugin_narrows_a_plain_pytest_invocation(mixed_repo: Path) -> None:
    _change_pricing(mixed_repo)
    proc = _pytest(mixed_repo, "--testsniper")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "testsniper: default mode, working tree vs HEAD" in out
    assert "selected 7 of 23 collected tests" in out
    assert (
        "tests/test_checkout.py: 6 of 14, narrowed by name usage"
        " and 1 affected conftest fixture" in out
    )
    assert "7 passed, 16 deselected" in out


def test_changing_shipping_selects_a_different_slice(mixed_repo: Path) -> None:
    shipping = mixed_repo / "store" / "shipping.py"
    shipping.write_text(shipping.read_text() + "\nEXPRESS_CENTS = 1999\n")
    proc = _pytest(mixed_repo, "--testsniper")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    # Both files import shipping; only the tests that use it survive.
    assert "tests/test_checkout.py: 2 of 14" in out
    assert "tests/test_shipping_rules.py: 6 of 6" not in out
    # A shipping change reaches nothing in tests/conftest.py, so the file that
    # is only reachable through a fixture is not selected at all.
    assert "tests/test_totals_report.py" not in out
    assert "8 passed, 15 deselected" in out


def test_a_test_added_to_a_test_file_is_the_only_one_selected(mixed_repo: Path) -> None:
    """A changed test file used to run in full; now its diff says which test.

    Nothing else in the repository changed, so the added test is the entire
    change and the other thirteen in the file have nothing to do with it.
    """
    checkout = mixed_repo / "tests" / "test_checkout.py"
    checkout.write_text(checkout.read_text() + "\n\ndef test_added():\n    assert True\n")
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "1 of 14 tests: narrowed by its own diff and name usage" in out
    assert "      test_added\n" in out
    assert "test_subtotal_sums_every_line" not in out


def test_a_changed_test_file_is_run_whole_in_safe_mode(mixed_repo: Path) -> None:
    checkout = mixed_repo / "tests" / "test_checkout.py"
    checkout.write_text(checkout.read_text() + "\n\ndef test_added():\n    assert True\n")
    proc = _run(mixed_repo, "--nodes", "--list", "--safe")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all tests: the test file itself changed" in proc.stdout


def test_an_affected_conftest_fixture_is_followed_across_files(mixed_repo: Path) -> None:
    """The committed conftest is affected by a pricing change.

    Only its taxed_total fixture reaches pricing, so narrowing continues and
    the one test that requests that fixture is selected through it, even
    though test_checkout.py never imports tests/conftest.py.
    """
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "6 of 13 tests: narrowed by name usage and 1 affected conftest fixture" in out
    assert "test_receipt_shows_the_taxed_total" in out
    # basket is a conftest fixture too, and a pricing change does not reach it.
    assert "test_receipt_lists_every_line" not in out


def test_an_affected_autouse_conftest_fixture_stops_narrowing(mixed_repo: Path) -> None:
    """A change to receipts reaches the autouse fixture, which runs for all."""
    _change_receipts(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "would run 19 of 19 tests" in out
    assert (
        "all tests: autouse fixture _fresh_currency in tests/conftest.py reaches the change" in out
    )


def test_module_level_code_in_a_conftest_stops_narrowing(mixed_repo: Path) -> None:
    """Import-time code in a conftest can configure state no test names."""
    (mixed_repo / "tests" / "conftest.py").write_text(
        "from store.pricing import TAX_RATE\n\nRATE_PERCENT = TAX_RATE * 100\n"
    )
    git(mixed_repo, "add", "-A")
    git(mixed_repo, "commit", "-q", "-m", "replace conftest")
    # TAX_RATE is module-level, so this change is not localizable to any one
    # symbol and the whole module stays affected. That is what puts the
    # conftest's own module-level code in play.
    pricing = mixed_repo / "store" / "pricing.py"
    pricing.write_text(pricing.read_text().replace("TAX_RATE = 0.075", "TAX_RATE = 0.08"))
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (
        "all tests: module-level code in tests/conftest.py uses an affected import" in proc.stdout
    )


def test_a_file_reached_only_through_a_fixture_is_selected(mixed_repo: Path) -> None:
    """tests/test_totals_report.py imports nothing a pricing change touches.

    Its one connection to pricing is the taxed_total fixture in
    tests/conftest.py. The import graph cannot see that file at all, so
    before file-level fixture selection it was never run.
    """
    _change_pricing(mixed_repo)
    proc = _run(mixed_repo, "--nodes", "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert (
        "tests/test_totals_report.py  [fixture] requests affected fixture taxed_total"
        " from tests/conftest.py" in out
    )
    # And it is still narrowed: only the test that asks for the fixture runs.
    assert "1 of 3 tests: narrowed by name usage and 1 affected conftest fixture" in out
    assert "test_the_taxed_total_is_rendered_as_dollars" in out
    assert "test_zero_renders_as_zero" not in out


def test_an_autouse_fixture_selects_a_file_that_imports_nothing_affected(
    mixed_repo: Path,
) -> None:
    """tests/test_shipping_rules.py imports only shipping, never receipts.

    The autouse fixture in tests/conftest.py calls reset_currency() from
    receipts for every test in the directory, so a receipts change does reach
    it. Selecting by import alone missed the whole file.
    """
    _change_receipts(mixed_repo)
    proc = _run(mixed_repo, "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert (
        "tests/test_shipping_rules.py  [fixture] autouse fixture _fresh_currency"
        " in tests/conftest.py reaches the change" in out
    )
    assert "would run 19 of 19 tests" in out
