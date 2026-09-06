#!/usr/bin/env bash
# Demo, in two parts.
#
# Part 1 uses the generated fixture project (402 tests) to show file-level
# selection: change one module, run only the test files that can reach it.
#
# Part 2 uses the mixed project, where one test file's tests use different
# modules, to show node-level selection: the same change reaches only part of
# that file, and the pytest plugin drops the rest at collection time.
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
testsniper --nodes --list
echo
echo "\$ pytest --testsniper"
python -m pytest --testsniper
