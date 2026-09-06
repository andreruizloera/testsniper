#!/usr/bin/env bash
# Demo, in two parts.
#
# Part 1 uses the generated fixture project (402 tests) to show file-level
# selection: change one module, run only the test files that can reach it.
#
# Part 2 uses the mixed project, where one test file's tests use different
# modules, to show node-level selection: the same change reaches only part of
# that file, and the pytest plugin drops the rest at collection time.
#
# Part 3 stays in the mixed project and changes a module that its conftest's
# autouse fixture reaches, so narrowing correctly gives up and says why.
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

echo "\$ testsniper --list"
testsniper --list
echo
echo "\$ testsniper --nodes --list"
nodes_out="$(testsniper --nodes --list)"
echo "$nodes_out"
echo
echo "\$ pytest --testsniper"
python -m pytest --testsniper

echo
echo "### Part 3: a fixture the test file never imports"
echo
echo "The pricing change above reaches tests/conftest.py, which the checkout"
echo "tests do not import. Only its taxed_total fixture reaches pricing, so"
echo "narrowing follows that one fixture instead of giving up on the directory."
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
expect "$autouse_out" "all tests: autouse fixture _fresh_currency in tests/conftest.py reaches the change"
echo
echo "Demo checks passed."
