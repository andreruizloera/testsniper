#!/usr/bin/env bash
# Demo: copy the fixture project (402 tests) to a temp dir, change one
# module, and let testsniper pick the tests that change can actually affect.
set -euo pipefail

if ! command -v testsniper >/dev/null 2>&1; then
    echo "testsniper is not on PATH."
    echo "From the repo root run: uv sync && uv run bash demo.sh"
    exit 1
fi

root="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cp -R "$root/examples/fixture_project" "$tmp/proj"
cd "$tmp/proj"
git init -q -b main
git add -A
git -c user.name=demo -c user.email=demo@example.com \
    -c commit.gpgsign=false commit -q -m "fixture baseline"

printf '\n\ndef extra() -> int:\n    return 42\n' >> fixture_lib/c4/layer1.py

echo "\$ testsniper"
testsniper
echo
echo "\$ testsniper --aggressive"
testsniper --aggressive
echo
echo "\$ testsniper --safe --list"
testsniper --safe --list
