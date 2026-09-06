#!/usr/bin/env bash
# Demo, in four parts.
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
set -euo pipefail

if ! command -v testsniper >/dev/null 2>&1; then
    echo "testsniper is not on PATH."
    echo "From the repo root run: uv sync && uv run bash demo.sh"
    exit 1
fi

root="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

setup() {
    cp -R "$root/examples/$1" "$tmp/$1"
    cd "$tmp/$1"
    git init -q -b main
    git add -A
    git -c user.name=demo -c user.email=demo@example.com \
        -c commit.gpgsign=false commit -q -m "baseline"
}

echo "### Part 1: file-level selection, 402-test fixture project"
echo
setup fixture_project
printf '\n\ndef extra() -> int:\n    return 42\n' >> fixture_lib/c4/layer1.py

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
printf '\n\ndef bulk_discount(cents: int) -> int:\n    return cents * 9 // 10\n' \
    >> store/pricing.py

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
printf '\n\ndef render_footer(note: str) -> str:\n    return f"-- {note}"\n' \
    >> store/receipts.py
echo "\$ testsniper --nodes --list   # after changing store/receipts.py instead"
autouse_out="$(testsniper --nodes --list)"
echo "$autouse_out"

# The README pastes these lines. Fail loudly rather than let them drift.
expect() {
    if ! printf '%s' "$1" | grep -qF -- "$2"; then
        echo
        echo "DEMO FAILED: expected to find: $2"
        exit 1
    fi
}
expect "$nodes_out" "7 of 13 tests: narrowed by name usage and 1 affected conftest fixture"
expect "$nodes_out" "test_receipt_shows_the_taxed_total"
expect "$nodes_out" "1 of 3 tests: narrowed by name usage and 1 affected conftest fixture"
expect "$file_out" \
    "tests/test_totals_report.py  [fixture] requests affected fixture taxed_total"
expect "$autouse_out" \
    "tests/test_shipping_rules.py  [fixture] autouse fixture _fresh_currency"
expect "$autouse_out" "all tests: autouse fixture _fresh_currency in tests/conftest.py reaches the change"
echo
echo "Demo checks passed."
