# testsniper

Run the tests your code change can actually affect.

[![CI](https://github.com/andreruizloera/testsniper/actions/workflows/ci.yml/badge.svg)](https://github.com/andreruizloera/testsniper/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

testsniper reads your git diff, builds a repository-wide import graph with
the `ast` module, and runs only the tests that can reach your change through
imports. It works at file level from the command line and, through its pytest
plugin, at the level of individual test functions. On the bundled 402-test
example project, changing one module runs 32 tests instead of 402:

```text
$ testsniper
Changed: fixture_lib/c4/layer1.py
Selected: tests/test_c4_layer1.py, tests/test_c4_layer2.py, tests/test_c4_api.py, tests/smoke/test_smoke.py
Running 32 of 402 tests...
................................                                         [100%]
32 passed in 0.32s
Skipped: 370 (not selected)
Selection confidence: High
```

That output is pasted verbatim from `demo.sh`; run it yourself.

### Down to individual tests

A file is a coarse unit. Real test files mix concerns: a checkout test file
touches pricing in some tests, shipping in others, and string formatting in
the rest. `testsniper --nodes` narrows inside each selected file to the test
functions that actually use the change, and the pytest plugin applies that at
collection time, where the node IDs are real:

```text
$ pytest --testsniper
============================= test session starts ==============================
testsniper: default mode, working tree vs HEAD
plugins: testsniper-0.1.0
collected 20 items / 12 deselected / 8 selected

tests/test_checkout.py ........                                          [100%]

---------------------------------- testsniper ----------------------------------
1 changed file(s), working tree vs HEAD
selected 8 of 20 collected tests
  tests/test_checkout.py: 8 of 14, narrowed by name usage
selection confidence: High
======================= 8 passed, 12 deselected in 0.67s =======================
```

Both blocks are real `demo.sh` output. The second is trimmed of the platform
and rootdir lines, and the timings of course differ from run to run; nothing
else is edited.

## Quickstart

```bash
git clone https://github.com/andreruizloera/testsniper
cd testsniper
uv sync
uv run bash demo.sh
```

The demo runs in two parts. Part 1 copies the generated example project (40
modules, 402 tests) to a temp directory, edits one module, and shows the
default, `--aggressive`, and `--safe --list` selections. Part 2 copies the
mixed example project, edits `store/pricing.py`, and shows the same change
narrowed to individual tests by `--nodes` and by the plugin.

## Why?

Large pytest suites make the feedback loop painful: you change one module
and wait for a thousand unrelated tests. Coverage-based selection tools
answer this well but need instrumented baseline runs. testsniper takes the
cheap static route instead: imports are almost always the channel through
which a Python change reaches a test, and the import graph can be built in
one pass with no test execution, no instrumentation, and no stored state. You
get a useful selection in well under a second, plus an honest confidence
rating for the cases static analysis cannot see.

## Installation

Not on PyPI yet. Install from git into the same environment that has your
project's pytest (testsniper invokes `python -m pytest` from its own
interpreter, so they must live together):

```bash
pip install git+https://github.com/andreruizloera/testsniper
```

Requires Python 3.12+ and git. Zero runtime dependencies beyond the
standard library; pytest is only needed in the target project. Installing
into that environment also registers the pytest plugin through the `pytest11`
entry point, so `pytest --testsniper` works with no further setup. The plugin
adds its flags and otherwise does nothing until you pass one.

## Usage

```bash
testsniper              # working tree vs HEAD (includes untracked files)
testsniper --staged     # staged changes only (git diff --cached)
testsniper HEAD~1       # working tree vs an arbitrary revision
testsniper --list       # print the selection, do not run pytest
testsniper --nodes      # narrow to individual test functions, not whole files
testsniper --safe       # over-select when in doubt
testsniper --aggressive # direct importers only, fastest loop
```

Exit code is pytest's exit code, so it drops into scripts and hooks as a
`pytest` replacement.

### The pytest plugin

The plugin is the same selection applied from inside pytest, so you keep your
own pytest invocation, your own arguments, and your own plugins:

```bash
pytest --testsniper                      # working tree vs HEAD
pytest --testsniper-ref main             # vs an arbitrary revision
pytest --testsniper-staged               # staged changes only
pytest --testsniper --testsniper-mode=aggressive
pytest -k slow --testsniper              # composes with everything else
```

It registers through the `pytest11` entry point and does nothing at all until
one of those flags is passed.

Working inside pytest is what buys node granularity. The command line can only
name files, because a file is the smallest thing you can name without knowing
what is in it. After collection every test is a real item with a real node ID,
so the plugin drops individual functions, and keeps every parametrized case of
the ones it keeps, without inventing any of those IDs from source.

Deselection happens after collection, which means the modules were imported
either way. A change that breaks an import still fails the run rather than
vanishing along with the tests that would have caught it.

`testsniper --nodes` is the same machinery from the other side: it runs the
analysis once, writes it to a temporary plan file, and hands that to the
plugin with `--testsniper-plan`, so the two entry points share one analysis
and one deselection path rather than drifting apart.

### How narrowing decides, and when it refuses

Inside a selected file, testsniper resolves each import to a module, marks the
bindings whose target is affected by the change, and asks per test function
whether any name it reads traces back to one of them. Usage follows the file's
own definitions, so a helper, a fixture reached through the parameter that
requests it, and a `self.other_method()` call all propagate.

The analysis refuses to narrow a file, and runs all of it, when:

- the test file itself changed, or it is in an `always_run` path, or it sits
  under a changed `conftest.py`
- a `conftest.py` that applies to it is itself affected, since its fixtures
  can reach any test there without being named in the file
- module-level code in it uses an affected import, since that can configure
  shared state no individual test mentions
- it star-imports an affected module, imports dynamically, reads names through
  `globals()`, `eval`, or `exec`, has an unresolvable relative import, or does
  not parse

Anything the analysis did not recognize is kept, not dropped: an item that has
no matching test function in the AST (a doctest, an item from a custom
collector) always runs. Every refusal prints its reason.

### Modes

| Mode | Selection | Changed conftest.py | Changed config or non-Python file |
| --- | --- | --- | --- |
| `--safe` | transitive closure, widened to every module in each changed module's package | selects its whole subtree | selects everything, with the reason printed |
| default | full transitive closure over the reverse import graph | selects its whole subtree | ignored, confidence drops to Low with a pointer to `--safe` |
| `--aggressive` | only tests that import a changed module directly | ignored, confidence drops to Low | ignored, confidence drops to Low |

All modes always include `always_run` paths and rank selected tests by
import distance, direct importers first. Node narrowing is orthogonal: the
mode decides which files are selected, and `--nodes` then narrows inside each
of them.

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
monkeypatching can all cross module boundaries invisibly. Node narrowing
adds a second such layer, since it reads names rather than executing them.
That is what the confidence rating, the refusal rules above, and `--safe`
are for, and why CI should still run the full suite.

## Architecture

```
src/testsniper/
  cli.py       argument parsing and output
  gitio.py     changed files from git (working tree, staged, or vs a ref)
  scanner.py   AST scan of every .py file: imports, star/dynamic flags
  graph.py     reverse import graph and BFS transitive closure
  indexer.py   test file discovery and test function counting
  selector.py  modes, conftest/config triggers, always_run, confidence
  nodes.py     per-test name-usage analysis inside a selected file
  plan.py      the JSON contract carrying a selection into pytest
  plugin.py    pytest plugin: deselect at collection time
  runner.py    pytest invocation on the selected files
```

The pipeline: diff -> changed modules -> reverse import graph (who imports
whom, transitively) -> test files in the closure, ranked by distance ->
optionally, the test functions inside them that read an affected import ->
pytest. Graph nodes are file paths, not module names, so name collisions
(every `conftest.py`) can only over-select, never under-select.

`nodes.py` is pure: it takes a root, a file, and a set of affected module
names, and returns a verdict. It knows nothing about git, pytest, or the
graph that produced the affected set. `plugin.py` is the only module that
imports pytest, and nothing imports `plugin.py`.

Two example projects are committed. `examples/fixture_project/` is generated
deterministically by `scripts/gen_fixture.py`: 10 independent import chains of
4 modules each, 10 tests per module, plus a smoke suite wired into
`always_run`. It shows file-level selection at scale, but every test in one of
its files uses the same module, so node narrowing has nothing to remove there.
`examples/mixed_project/` exists for that: one small store whose checkout test
file mixes pricing, shipping, and formatting tests, so a pricing change reaches
7 of its 13 test functions and none of the other file.

## Limitations

- pytest only. File-level selection is the default; node-level selection
  needs `--nodes` or the plugin.
- Static analysis: dynamic imports, plugin registries, and entry points
  are invisible; the confidence rating tells you when that matters.
- Node narrowing reads names, so it cannot see through `getattr`, string
  dispatch, or a module named only by a string (`pytest.importorskip("x")`).
  It sees `globals`, `eval`, `exec`, star imports of the change, and dynamic
  imports, and refuses to narrow when it finds them, but `getattr` is too
  common in test code to treat as a signal and is deliberately ignored.
- Fixtures are followed inside a file, not across files. A fixture in a
  `conftest.py` is handled by not narrowing at all when that conftest is
  affected, which is safe but coarse: one affected conftest turns off
  narrowing for its whole subtree.
- A file whose imports reach the change but whose tests never use them is
  dropped entirely. That is the intended behavior and it is the case most
  likely to surprise; `--list` names every selected function so you can check.
- Test counts are counted from the AST, so parametrized tests count once
  per function; the run totals from pytest are exact.
- pytest output is captured and reprinted after the run finishes rather
  than streamed live.
- testsniper must share an environment with the target project's pytest.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Highlights: PyPI release, fixture-graph
awareness across conftest files, import graph caching, and coverage-map
hybrid selection.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Development is uv-based:
`uv sync`, `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`.

GitHub topics: `testing`, `pytest`, `developer-tools`, `test-selection`, `ci`.

## License

MIT, see [LICENSE](LICENSE).
