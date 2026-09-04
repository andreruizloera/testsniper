"""Deterministically regenerate examples/fixture_project.

The fixture is a small library of 10 independent import chains
(base -> layer1 -> layer2 -> api) with 10 trivial tests per module,
plus a smoke suite wired into [tool.testsniper] always_run. The output
is committed; run this script only to regenerate it from scratch.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "examples" / "fixture_project"

CHAINS = 10
LAYERS = ["base", "layer1", "layer2", "api"]
TESTS_PER_FILE = 10

PYPROJECT = """\
[project]
name = "fixture-project"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.testsniper]
always_run = ["tests/smoke"]
"""

CONFTEST = '"""Root conftest so pytest puts the project root on sys.path."""\n'

SMOKE = '''\
"""Smoke tests, wired into [tool.testsniper] always_run."""

from fixture_lib.c0.api import api_value


def test_smoke_api_chain_zero() -> None:
    assert api_value() == 103


def test_smoke_arithmetic() -> None:
    assert 1 + 1 == 2
'''


def module_source(chain: int, layer_index: int) -> str:
    layer = LAYERS[layer_index]
    if layer_index == 0:
        return (
            f'"""Chain c{chain}, {layer} module."""\n\n\n'
            f"def {layer}_value() -> int:\n"
            f"    return {100 + chain}\n"
        )
    prev = LAYERS[layer_index - 1]
    return (
        f'"""Chain c{chain}, {layer} module."""\n\n'
        f"from fixture_lib.c{chain}.{prev} import {prev}_value\n\n\n"
        f"def {layer}_value() -> int:\n"
        f"    return {prev}_value() + 1\n"
    )


def test_source(chain: int, layer_index: int) -> str:
    layer = LAYERS[layer_index]
    expected = 100 + chain + layer_index
    lines = [
        f'"""Tests for fixture_lib.c{chain}.{layer}."""\n',
        f"from fixture_lib.c{chain}.{layer} import {layer}_value\n",
    ]
    for k in range(TESTS_PER_FILE):
        lines.append(
            f"\ndef test_c{chain}_{layer}_{k:02d}() -> None:\n"
            f"    assert {layer}_value() + {k} == {expected + k}\n"
        )
    return "\n".join(lines)


def main() -> None:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    lib = FIXTURE / "fixture_lib"
    tests = FIXTURE / "tests"
    smoke = tests / "smoke"
    smoke.mkdir(parents=True)
    lib.mkdir(parents=True)

    (FIXTURE / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (FIXTURE / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    (FIXTURE / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (lib / "__init__.py").write_text('"""Generated fixture library."""\n', encoding="utf-8")
    (smoke / "test_smoke.py").write_text(SMOKE, encoding="utf-8")

    for chain in range(CHAINS):
        pkg = lib / f"c{chain}"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(f'"""Chain c{chain}."""\n', encoding="utf-8")
        for i, layer in enumerate(LAYERS):
            (pkg / f"{layer}.py").write_text(module_source(chain, i), encoding="utf-8")
            (tests / f"test_c{chain}_{layer}.py").write_text(
                test_source(chain, i), encoding="utf-8"
            )

    n_tests = CHAINS * len(LAYERS) * TESTS_PER_FILE + 2
    print(f"generated fixture with {CHAINS * len(LAYERS)} modules and {n_tests} tests")


if __name__ == "__main__":
    main()
