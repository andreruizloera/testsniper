#!/usr/bin/env bash
# Demo, in seven parts.
#
# Part 1 uses the generated fixture project (402 tests) to show file-level
# selection: change one module, run only the test files that can reach it.
#
# Part 2 uses the mixed project, where one test file's tests use different
# modules, to show node-level selection: the same change reaches only part of
# that file, and the pytest plugin drops the rest at collection time.
#
# Part 3 shows the other direction, in the same project and on the same
# change: a test file that imports nothing affected and reaches the change
# only through a conftest fixture, which no import graph can see.
#
# Part 4 changes a module that the conftest's autouse fixture reaches, which
# applies to every test underneath it, so the whole directory is selected and
# narrowing gives up with the reason.
#
# Part 5 changes the conftest.py itself, twice: once in one fixture body, and
# once in a comment. The old content comes out of git, so the first selects
# the tests that ask for that fixture and the second selects nothing.
# Part 6 changes a TEST file itself, and reads it the same way: an added test
# is the only test selected, and an edited helper method selects the methods
# that call it.
#
# Part 7 shows the unit below the module: a change to one symbol of a changed
# module does not reach a test that imports a different symbol of it, and a
# function nothing calls reaches no existing test at all.
#
# Every change below edits an EXISTING definition unless a part is about
# adding one, because appending an inert function is now correctly a change
# that reaches nothing, and would demonstrate nothing.
set -euo pipefail

if ! command -v testsniper >/dev/null 2>&1; then
    echo "testsniper is not on PATH."
    echo "From the repo root run: uv sync && uv run bash demo.sh"
    exit 1
fi

root="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

setup_n=0
setup() {
    # A fresh copy per call, so two parts using the same example project do
    # not nest one inside the other.
    setup_n=$((setup_n + 1))
    cp -R "$root/examples/$1" "$tmp/$setup_n-$1"
    cd "$tmp/$setup_n-$1"
    git init -q -b main
    git add -A
    git -c user.name=demo -c user.email=demo@example.com \
        -c commit.gpgsign=false commit -q -m "baseline"
}

echo "### Part 1: file-level selection, 402-test fixture project"
echo
setup fixture_project
python - <<'EOF'
import pathlib

path = pathlib.Path("fixture_lib/c4/layer1.py")
# Behaviour-preserving on purpose: the point of part 1 is which tests are
# SELECTED, and a demo whose tests fail would say nothing about that.
path.write_text(path.read_text().replace("return base_value() + 1", "return 1 + base_value()"))
EOF

echo "\$ testsniper"
testsniper
echo
echo "\$ testsniper --aggressive"
testsniper --aggressive
echo
echo "\$ testsniper --safe --list"
testsniper --safe --list

echo
echo "### Part 2: node-level selection, mixed project"
echo
setup mixed_project
python - <<'EOF'
import pathlib

path = pathlib.Path("store/pricing.py")
path.write_text(
    path.read_text().replace(
        "    return int(cents + cents * TAX_RATE + 0.5)",
        "    return int(cents + cents * TAX_RATE + 0.5) if cents else 0",
    )
)
EOF

echo "\$ testsniper --nodes --list"
nodes_out="$(testsniper --nodes --list)"
echo "$nodes_out"
echo
echo "\$ pytest --testsniper"
python -m pytest --testsniper

echo
echo "### Part 3: a file selected through a fixture it never imports"
echo
echo "Same pricing change. tests/test_totals_report.py imports one formatting"
echo "helper and nothing else, so no import path connects it to pricing at all."
echo "It asks for the taxed_total fixture in tests/conftest.py, and that does."
echo
echo "\$ testsniper --list"
file_out="$(testsniper --list)"
echo "$file_out"

echo
echo "### Part 4: when the fixture applies to every test underneath"
echo
echo "A change to receipts reaches the autouse fixture, which runs for every"
echo "test in the directory whether it asks for it or not. So the whole"
echo "directory is selected, including the file that imports only shipping."
echo
git checkout -q -- store/pricing.py
python - <<'EOF'
import pathlib

path = pathlib.Path("store/receipts.py")
path.write_text(
    path.read_text().replace(
        '    _currency["symbol"] = DEFAULT_SYMBOL\n\n\ndef format_cents',
        '    _currency.update({"symbol": DEFAULT_SYMBOL})\n\n\ndef format_cents',
    )
)
EOF
echo "\$ testsniper --nodes --list   # after changing store/receipts.py instead"
autouse_out="$(testsniper --nodes --list)"
echo "$autouse_out"

echo
echo "### Part 5: a changed conftest.py, read through its own diff"
echo
echo "The conftest is the change. Its previous content comes from git, so the"
echo "fixture graph can be built twice and compared: only taxed_total moved."
echo
setup mixed_project
python - <<'EOF'
import pathlib

path = pathlib.Path("tests/conftest.py")
path.write_text(
    path.read_text().replace(
        "    return order_total(basket)",
        "    return order_total(basket) + 0",
    )
)
EOF
echo "\$ testsniper --nodes --list"
changed_out="$(testsniper --nodes --list)"
echo "$changed_out"
echo
echo "And the same file with only a comment added, which changes no behavior:"
echo
git checkout -q -- tests/conftest.py
python - <<'EOF'
import pathlib

path = pathlib.Path("tests/conftest.py")
path.write_text(
    path.read_text().replace(
        "    return list(BASKET)",
        "    # the basket is copied so a test cannot mutate the module constant\n"
        "    return list(BASKET)",
    )
)
EOF
echo "\$ testsniper --list"
comment_out="$(testsniper --list)"
echo "$comment_out"

echo
echo "### Part 6: a changed test file, read through its own diff"
echo
echo "The test file is the change. A new test is the only thing the change"
echo "reaches, and a helper method inside a class reaches the methods that"
echo "call it and not the sibling that does not."
echo
setup mixed_project
printf '\n\ndef test_shipping_is_free_over_ten_kilos():\n    assert shipping_cost(10000) == 0\n' \
    >> tests/test_checkout.py
echo "\$ testsniper --nodes --list"
added_out="$(testsniper --nodes --list)"
echo "$added_out"
echo
echo "And editing the _render helper the class shares:"
echo
git checkout -q -- tests/test_checkout.py
python - <<'EOF'
import pathlib

path = pathlib.Path("tests/test_checkout.py")
path.write_text(
    path.read_text().replace(
        'return render_receipt("Ada", [("Shipping", 599)])',
        'return render_receipt("Ada", [("Shipping", 600 - 1)])',
    )
)
EOF
echo "\$ testsniper --nodes --list"
helper_out="$(testsniper --nodes --list)"
echo "$helper_out"

echo
echo "### Part 7: a change to one symbol does not reach a test that uses another"
echo
echo "tests/test_checkout.py imports both line_total and price_with_tax. The"
echo "pricing change in part 2 rewrote price_with_tax only, and line_total does"
echo "not call it, so test_line_total_multiplies is not in that list above."
echo "Adding a whole new function is the same argument taken further: nothing"
echo "calls it, so no existing test can see it."
echo
setup mixed_project
printf '\n\ndef bulk_discount(cents: int) -> int:\n    return cents * 9 // 10\n' \
    >> store/pricing.py
echo "\$ testsniper --nodes --list   # after APPENDING a function to store/pricing.py"
added_fn_out="$(testsniper --nodes --list)"
echo "$added_fn_out"

# The README pastes these lines. Fail loudly rather than let them drift.
expect() {
    if ! printf '%s' "$1" | grep -qF -- "$2"; then
        echo
        echo "DEMO FAILED: expected to find: $2"
        exit 1
    fi
}
# A claim that narrowing DROPPED a test is a claim about what is absent, and
# only an absence check can test it. `expect` alone would pass on a run that
# selected everything.
expect_absent() {
    if printf '%s' "$1" | grep -qF -- "$2"; then
        echo
        echo "DEMO FAILED: expected NOT to find: $2"
        exit 1
    fi
}
expect "$nodes_out" "6 of 13 tests: narrowed by name usage and 1 affected conftest fixture"
expect "$nodes_out" "test_price_with_tax_rounds_half_up"
# The whole point of symbol narrowing: line_total is in the same changed
# module and is not reached by a change to price_with_tax.
expect_absent "$nodes_out" "test_line_total_multiplies"
expect "$nodes_out" "test_receipt_shows_the_taxed_total"
expect "$nodes_out" "1 of 3 tests: narrowed by name usage and 1 affected conftest fixture"
expect "$file_out" \
    "tests/test_totals_report.py  [fixture] requests affected fixture taxed_total"
expect "$autouse_out" \
    "tests/test_shipping_rules.py  [fixture] autouse fixture _fresh_currency"
expect "$autouse_out" "all tests: autouse fixture _fresh_currency in tests/conftest.py reaches the change"
expect "$changed_out" \
    "Note: tests/conftest.py is changed through taxed_total; selecting the tests that request those fixtures"
expect "$changed_out" "Selected (would run 2 of 19 tests):"
expect "$changed_out" \
    "tests/test_checkout.py  [fixture] requests changed fixture taxed_total from tests/conftest.py"
expect "$changed_out" "test_receipt_shows_the_taxed_total"
expect "$comment_out" "Changed: tests/conftest.py"
expect "$comment_out" "Selected: none"
expect "$added_out" "1 of 14 tests: narrowed by its own diff and name usage"
expect "$added_out" "test_shipping_is_free_over_ten_kilos"
expect "$helper_out" "2 of 13 tests: narrowed by its own diff and name usage"
expect "$helper_out" "TestReceiptFormatting::test_amounts_are_dollars_and_cents"
expect "$helper_out" "TestReceiptFormatting::test_header_names_the_customer"
expect "$added_fn_out" "Selected: tests/test_checkout.py"
expect "$added_fn_out" "3 of 13 tests: narrowed by name usage and 1 affected conftest fixture"
expect_absent "$added_fn_out" "test_price_with_tax_rounds_half_up"
expect_absent "$added_fn_out" "test_line_total_multiplies"
echo
echo "Demo checks passed."
