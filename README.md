# testsniper

Run the tests your code change can actually affect.

[![CI](https://github.com/andreruizloera/testsniper/actions/workflows/ci.yml/badge.svg)](https://github.com/andreruizloera/testsniper/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

testsniper reads your git diff, builds a repository-wide import graph with
the `ast` module, and hands pytest only the test files that can reach your
change through imports. On the bundled 402-test example project, changing
one module runs 32 tests instead of 402:

```text
$ testsniper
Changed: fixture_lib/c4/layer1.py
Selected: tests/test_c4_layer1.py, tests/test_c4_layer2.py, tests/test_c4_api.py, tests/smoke/test_smoke.py
Running 32 of 402 tests...
................................                                         [100%]
32 passed in 0.06s
Skipped: 370 (not selected)
Selection confidence: High
```

That output is pasted verbatim from `demo.sh`; run it yourself.

## Quickstart

```bash
git clone https://github.com/andreruizloera/testsniper
cd testsniper
uv sync
uv run bash demo.sh
```

The demo copies the example project (40 modules, 402 tests) to a temp
directory, edits one module, and shows the default, `--aggressive`, and
`--safe --list` selections.

## Why?

Large pytest suites make the feedback loop painful: you change one module
and wait for a thousand unrelated tests. Coverage-based selection tools
answer this well but need instrumented baseline runs. testsniper takes the
cheap static route instead: imports are almost always the channel through
which a Python change reaches a test, and the import graph can be built in
one pass with no test execution, no plugins, and no state. You get a
useful selection in well under a second, plus an honest confidence rating
for the cases static analysis cannot see.

## Installation

Not on PyPI yet. Install from git into the same environment that has your
project's pytest (testsniper invokes `python -m pytest` from its own
interpreter, so they must live together):

```bash
pip install git+https://github.com/andreruizloera/testsniper
```

Requires Python 3.12+ and git. Zero runtime dependencies beyond the
standard library; pytest is only needed in the target project.

## Usage

```bash
testsniper              # working tree vs HEAD (includes untracked files)
testsniper --staged     # staged changes only (git diff --cached)
testsniper HEAD~1       # working tree vs an arbitrary revision
testsniper --list       # print the selection, do not run pytest
testsniper --safe       # over-select when in doubt
testsniper --aggressive # direct importers only, fastest loop
```

Exit code is pytest's exit code, so it drops into scripts and hooks as a
`pytest` replacement.

### Modes

| Mode | Selection | Changed conftest.py | Changed config or non-Python file |
| --- | --- | --- | --- |
| `--safe` | transitive closure, widened to every module in each changed module's package | selects its whole subtree | selects everything, with the reason printed |
| default | full transitive closure over the reverse import graph | selects its whole subtree | ignored, confidence drops to Low with a pointer to `--safe` |
| `--aggressive` | only tests that import a changed module directly | ignored, confidence drops to Low | ignored, confidence drops to Low |

All modes always include `always_run` paths and rank selected tests by
import distance, direct importers first.

### Configuration

```toml
[tool.testsniper]
always_run = ["tests/smoke/"]
```

Tests under `always_run` paths run on every invocation regardless of the
diff. Test discovery follows pytest conventions (`test_*.py` and
`*_test.py`) under `testpaths` from `pyproject.toml` or `pytest.ini`,
falling back to `tests/`, then the whole repository.

### Selection confidence

Every run prints a confidence rating with reasons:

- High: every import in the repository resolved statically.
- Medium: something can hide dependencies, for example star imports,
  `importlib.import_module` or `__import__` calls, unresolved relative
  imports, a changed module that no test reaches, or aggressive mode
  itself (it skips transitive importers on purpose).
- Low: files failed to parse, or changed pytest config and non-Python
  files were left out of the analysis.

A changed module that no test imports is always reported:

```text
Warning: no test reaches changed module pkg/lonely.py
```

To be plain about it: skipped tests are skipped because no static import
path connects them to your change, not because they provably cannot fail.
Runtime dispatch, fixtures with side effects, data files, and
monkeypatching can all cross module boundaries invisibly. That is what
the confidence rating and `--safe` are for, and why CI should still run
the full suite.

## Architecture

```
src/testsniper/
  cli.py       argument parsing and output
  gitio.py     changed files from git (working tree, staged, or vs a ref)
  scanner.py   AST scan of every .py file: imports, star/dynamic flags
  graph.py     reverse import graph and BFS transitive closure
  indexer.py   test file discovery and test function counting
  selector.py  modes, conftest/config triggers, always_run, confidence
  runner.py    pytest invocation on the selected files
```

The pipeline: diff -> changed modules -> reverse import graph (who imports
whom, transitively) -> test files in the closure, ranked by distance ->
pytest on exactly those files. Graph nodes are file paths, not module
names, so name collisions (every `conftest.py`) can only over-select,
never under-select.

The example project under `examples/fixture_project/` is generated
deterministically by `scripts/gen_fixture.py` and committed: 10
independent import chains of 4 modules each, 10 tests per module, plus a
smoke suite wired into `always_run`.

## Limitations

- pytest only, and file-level selection only (no single-test node IDs).
- Static analysis: dynamic imports, plugin registries, and entry points
  are invisible; the confidence rating tells you when that matters.
- Test counts are counted from the AST, so parametrized tests count once
  per function; the run totals from pytest are exact.
- pytest output is captured and reprinted after the run finishes rather
  than streamed live.
- testsniper must share an environment with the target project's pytest.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Highlights: PyPI release, a pytest plugin
mode with test-node granularity, import graph caching, and coverage-map
hybrid selection.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Development is uv-based:
`uv sync`, `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`.

GitHub topics: `testing`, `pytest`, `developer-tools`, `test-selection`, `ci`.

## License

MIT, see [LICENSE](LICENSE).
