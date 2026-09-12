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
collected 23 items / 17 deselected / 6 selected

tests/test_checkout.py .....                                             [ 83%]
tests/test_totals_report.py .                                            [100%]

---------------------------------- testsniper ----------------------------------
1 changed file(s), working tree vs HEAD
selected 6 of 23 collected tests
  tests/test_checkout.py: 5 of 14, narrowed by name usage and 1 affected conftest fixture
  tests/test_totals_report.py: 1 of 3, narrowed by name usage and 1 affected conftest fixture
selection confidence: High
======================= 6 passed, 17 deselected in 0.14s =======================
```

Both blocks are real `demo.sh` output. The second is trimmed of the platform,
rootdir, configfile, and testpaths lines, and the timings of course differ from
run to run; nothing else is edited.

### The changed symbol, not the changed module

A module is a coarse unit too. `tests/test_checkout.py` imports both
`line_total` and `price_with_tax` from `store/pricing.py`; a change to
`price_with_tax` cannot reach a test that only calls `line_total`, because
`line_total` does not call it. testsniper reads the changed module's own diff,
works out which of its top-level names the change can reach, and treats an
import of any other name as innocent.

The same question is asked at every hop, not just the first. `store/orders.py`
imports pricing and has no diff of its own, so there is nothing to read there;
what testsniper does instead is work out which of *its* names read an affected
name of something it imports. `order_total` calls `price_with_tax` and
`subtotal` does not, so a test that calls `subtotal` is dropped as well.

Taken one step further, appending a whole new function to a module reaches
nothing at all. The file is still selected, because it still imports the
changed module, and every test inside it is dropped:

```text
$ testsniper --nodes --list   # after APPENDING a function to store/pricing.py
Changed: store/pricing.py
Selected: tests/test_checkout.py
Selected (would run 0 of 19 tests):
  tests/test_checkout.py  [distance 1] imports a changed module
    0 of 13 tests: narrowed by name usage
Selection confidence: High
```

Nothing calls the new function anywhere in the import graph, so no existing
test can see it, and `tests/test_totals_report.py` is not selected at all: the
conftest fixture that used to carry the change to it reaches pricing through
`store/orders.py`, and nothing in `store/orders.py` reads the new name either.

Definitions are compared as parsed syntax, so reflowing a line or editing a
comment inside a function reaches nothing, and a docstring edit does count,
since `--doctest-modules` can collect one. Usage propagates inside a module the
same way it propagates between modules: if `line_total` called
`price_with_tax`, editing `price_with_tax` brings both names back.

Propagation is refused rather than guessed wherever the answer would not be
sound: a star import, an unresolved relative import, a dynamic import, a
module-level `__getattr__`, module-level code that reads something affected, an
import cycle, and a package whose `__init__` is affected and runs on the way to
a submodule. A refused module keeps every one of its symbols affected, and the
run says which modules those were and why rather than silently widening.

### Fixtures the test file never imports

Fixtures are the usual way a change reaches a test without the test file
importing anything, so testsniper resolves them across files the way pytest
does, in both directions: which tests inside a selected file the change
reaches, and which files it reaches that no import path connects to at all.

```text
$ testsniper --nodes --list
Changed: store/pricing.py
Note: tests/conftest.py is affected through taxed_total; selecting the tests that request those fixtures
Selected: tests/test_checkout.py, tests/test_totals_report.py
Selected (would run 6 of 19 tests):
  tests/test_checkout.py  [distance 1] imports a changed module
    5 of 13 tests: narrowed by name usage and 1 affected conftest fixture
      test_order_total_applies_tax
      test_price_with_tax_of_zero_is_zero
      test_price_with_tax_rejects_a_negative_price
      test_price_with_tax_rounds_half_up
      test_receipt_shows_the_taxed_total
  tests/test_totals_report.py  [fixture] requests affected fixture taxed_total from tests/conftest.py
    1 of 3 tests: narrowed by name usage and 1 affected conftest fixture
      test_the_taxed_total_is_rendered_as_dollars
Selection confidence: High
```

Two things there come from the fixture graph rather than the import graph.
`test_receipt_shows_the_taxed_total` is kept inside a file it shares with
dropped tests, because it requests the `taxed_total` fixture, which is defined
in `tests/conftest.py` and reaches pricing through `store.orders`. And
`tests/test_totals_report.py` is selected at all only for that reason: it
imports one formatting helper, no import path connects it to pricing, and it
asks for the same fixture. `[fixture]` rather than `[distance N]` is how the
output says so. The `basket` fixture next to `taxed_total` does not reach
pricing, so the tests that ask only for that one are still dropped, in both
files.

When the change reaches something in a conftest that applies to every test
underneath it, that is not one fixture any more, and the whole directory is
selected with the reason:

```text
$ testsniper --nodes --list   # after changing store/receipts.py instead
Changed: store/receipts.py
Note: autouse fixture _fresh_currency in tests/conftest.py reaches the change, so every test it applies to is selected
Selected: tests/test_checkout.py, tests/test_totals_report.py, tests/test_shipping_rules.py
Selected (would run 19 of 19 tests):
  tests/test_checkout.py  [distance 1] imports a changed module
    all tests: autouse fixture _fresh_currency in tests/conftest.py reaches the change
  tests/test_totals_report.py  [distance 1] imports a changed module
    all tests: autouse fixture _fresh_currency in tests/conftest.py reaches the change
  tests/test_shipping_rules.py  [fixture] autouse fixture _fresh_currency in tests/conftest.py reaches the change
    all tests: autouse fixture _fresh_currency in tests/conftest.py reaches the change
Selection confidence: High
```

`tests/test_shipping_rules.py` imports only `store.shipping` and never
mentions receipts or that fixture. It runs because `_fresh_currency` is
autouse: it calls `reset_currency()` from the changed module before every test
in the directory, asked for or not. Selecting the subtree is the honest answer
there, and it is the cost of this channel; "How selection follows fixtures"
below lists exactly when it is paid.

When the `conftest.py` is itself what changed, its previous content comes out
of git and the fixture graph is built twice, so the same per-fixture answer
applies to the diff:

```text
$ testsniper --nodes --list   # after editing the taxed_total fixture itself
Changed: tests/conftest.py
Note: tests/conftest.py is changed through taxed_total; selecting the tests that request those fixtures
Selected: tests/test_checkout.py, tests/test_totals_report.py
Selected (would run 2 of 19 tests):
  tests/test_checkout.py  [fixture] requests changed fixture taxed_total from tests/conftest.py
    1 of 13 tests: narrowed by name usage and 1 affected conftest fixture
      test_receipt_shows_the_taxed_total
  tests/test_totals_report.py  [fixture] requests changed fixture taxed_total from tests/conftest.py
    1 of 3 tests: narrowed by name usage and 1 affected conftest fixture
      test_the_taxed_total_is_rendered_as_dollars
Selection confidence: High
```

Two of nineteen, where a changed conftest used to mean all nineteen with
narrowing switched off. Definitions are compared as parsed syntax rather than
as text, so a change the AST cannot see selects nothing at all:

```text
$ testsniper --list   # after adding one comment inside a fixture
Changed: tests/conftest.py
Selected: none
Selected (would run 0 of 19 tests):
Selection confidence: High
```

### When the test file is the change

A changed test file used to be the last place a diff was read as a whole
file: it ran in full, even though the diff already said which of its functions
moved. It is now read exactly the way a changed `conftest.py` is, against its
own previous content:

```text
$ testsniper --nodes --list   # after adding one test to test_checkout.py
Changed: tests/test_checkout.py
Selected: tests/test_checkout.py
Selected (would run 1 of 20 tests):
  tests/test_checkout.py  [distance 0] changed test file
    1 of 14 tests: narrowed by its own diff and name usage
      test_shipping_is_free_over_ten_kilos
Selection confidence: High
```

One of fourteen, where the whole file used to run. Taint spreads from the diff
the way it spreads from an import, so this is not only about tests that moved
themselves. Editing the `_render` helper that `TestReceiptFormatting` shares
selects the two methods that call it, and not the third, which does not:

```text
$ testsniper --nodes --list   # after editing one helper method
Changed: tests/test_checkout.py
Selected: tests/test_checkout.py
Selected (would run 2 of 19 tests):
  tests/test_checkout.py  [distance 0] changed test file
    2 of 13 tests: narrowed by its own diff and name usage
      TestReceiptFormatting::test_amounts_are_dollars_and_cents
      TestReceiptFormatting::test_header_names_the_customer
Selection confidence: High
```

A class is compared in two parts, because its body is not like its methods.
Bases, decorators, and class-body statements are shared by every test on the
class, so a move in any of them selects all of them; the methods are then
compared one at a time. The whole file still runs, with the reason, when the
diff cannot be localized: module-level code moved or reads something that did,
an autouse fixture or a `pytest_generate_tests` hook changed or was deleted, a
star import changed, or there is no readable previous content, which is the
case for a brand new test file. `--safe` runs a changed test file whole
whenever it changed at all.

### Tests that run the tool instead of importing it

A command-line end-to-end test starts a process. It imports none of the code
it exercises, so the import graph connects it to nothing, and a change that
broke the command line used to select none of those tests.

testsniper found this in itself. Breaking `cli.main` on the path that only a
real invocation takes, and leaving the path the unit tests use intact, gave a
selection that was green while the suite was not. Both blocks below are
complete, not excerpted, and the only difference in the first three lines is
the selection itself. The first is run at the commit before this feature:

```text
$ testsniper --list       # before: the subprocess tests are invisible
Changed: src/testsniper/cli.py
Note: symbol narrowing gave up on 2 module(s) (module-level code in src/testsniper/__main__.py reads something affected; it runs on import; module-level code in src/testsniper/cli.py reads something the diff changed); every symbol in them stays affected
Selected: tests/test_cli.py
Selected (would run 19 of 302 tests):
  tests/test_cli.py  [distance 1] imports a changed module
Selection confidence: High
```

`tests/test_cli.py` calls `main([...])` in process, so it passes: `19 passed`.
The three files that run `python -m testsniper` for real were never selected,
and the full suite reported `22 failed, 280 passed`, every one of the 22 in
those three files. Note that the widening the `Note:` line describes did not
help at all. It marks every symbol of `cli.py` and `__main__.py` affected, and
still misses all 22, because what is missing is not a symbol but the edge.

A `python -m` target is now read back out of the argument vector and treated
as the dependency it is:

```text
$ testsniper --list       # after: the same break, the same repository
Changed: src/testsniper/cli.py
Note: symbol narrowing gave up on 2 module(s) (module-level code in src/testsniper/__main__.py reads something affected; it runs on import; module-level code in src/testsniper/cli.py reads something the diff changed); every symbol in them stays affected
Selected: tests/test_cli.py, tests/test_cross_module_symbols.py, tests/test_e2e_fixture.py, tests/test_e2e_mixed.py, tests/test_subprocess_entrypoint.py
Selected (would run 48 of 321 tests):
  tests/test_cli.py  [distance 1] imports a changed module
  tests/test_cross_module_symbols.py  [distance 2] imports it transitively (distance 2)
  tests/test_e2e_fixture.py  [distance 2] imports it transitively (distance 2)
  tests/test_e2e_mixed.py  [distance 2] imports it transitively (distance 2)
  tests/test_subprocess_entrypoint.py  [distance 2] imports it transitively (distance 2)
Selection confidence: High
```

Running that selection reports `26 failed, 22 passed`; running the whole suite
reports `26 failed, 295 passed`. The same 26, so nothing is missed. The count
moved from 22 to 26 because this feature's own test file did not exist in the
before run: the failures are 6 in `test_cross_module_symbols.py`, 4 in
`test_e2e_fixture.py` and 12 in `test_e2e_mixed.py`, unchanged from the before
run, plus 4 in the new `test_subprocess_entrypoint.py`.

The reason column in that block is from the commit it was run at. Its four
subprocess lines now read `runs it in a subprocess, transitively (distance 2)`:
a reason saying "imports" about a file whose only import is `subprocess` was
false, and was corrected once console scripts made the same wording appear
about a test that imports nothing at all. A file whose own step toward the
change is an import keeps the import wording.

The reading is deliberately narrow. The call has to be named like one of the
`subprocess` process starters (`run`, `Popen`, `call`, `check_call`,
`check_output`, `getoutput`, `getstatusoutput`), matched on the bare name so
that `from subprocess import run` is seen too, which does mean a same-named
method on something else is also read. That costs nothing, because the payoff
is a dotted name that has to match a file in your repository to mean anything.
Only a literal `-m` followed by a literal
module name is matched, and `python -m pkg` records
both `pkg` and `pkg.__main__`, since that is what the interpreter runs. A
module name held in a variable or built with an f-string is refused rather
than guessed at, and a shell string command is not split.

### Tests that run the tool through its console script

Most command-line tests do not spell out `python -m`. They run the name the
tool is installed under, `subprocess.run(["mytool", "--list"])`, and that name
is not a module. It is a program an installer generated from one line of
packaging metadata, `mytool = "mytool.cli:main"`, whose whole job is to import
`mytool.cli` and call `main`. testsniper reads that metadata and treats running
the program as the import it is.

Measured on a small project installed with `uv pip install -e` into a fresh
virtualenv, so the `greet` on PATH is the installer's own wrapper. The project
declares `greet = "pkg.cli:main"` in `[project.scripts]` and has two tests: one
runs `subprocess.run(["greet"])` and imports nothing, the other imports an
unrelated module. `pkg/cli.py` was changed so the script prints the wrong
greeting. Before, at the previous commit:

```text
$ testsniper --list
Changed: pkg/cli.py
Selected: none
Selected (would run 0 of 2 tests):
Warning: no test reaches changed module pkg/cli.py
Selection confidence: Medium
  - no test imports these changed modules: pkg/cli.py
```

`testsniper` ran nothing and exited 0, while `pytest -q` on the same tree exited
1 with `1 failed, 1 passed`. After:

```text
$ testsniper --list
Changed: pkg/cli.py
Selected: tests/test_cli_script.py
Selected (would run 1 of 2 tests):
  tests/test_cli_script.py  [distance 1] runs a changed module in a subprocess
Selection confidence: High
```

`testsniper` now runs that one test, reports `1 failed`, and exits 1, and the
whole suite still reports `1 failed, 1 passed`: the same failure.

The after half is also part 8 of `demo.sh`, so CI re-runs it on every push, on
the same layout in `examples/script_project`. There the `greet` wrapper is
written by the demo, the way this project's own tests write it, rather than by
an installer. The demo fails the build if `Changed: pkg/cli.py`,
`Selected (would run 1 of 2 tests):` or the reason line above changes, if
`tests/test_other.py` is selected, if both tests do not pass before the change,
or if the selected run does not fail on the changed greeting and exit 1. The
before half was measured once, as described, and is not re-run.

The names come from `[project.scripts]` and `[project.gui-scripts]`,
`[tool.poetry.scripts]` (a string, or a table whose `type` is `console`), and
`console_scripts` or `gui_scripts` under `[options.entry_points]` in
`setup.cfg`, read from every `pyproject.toml` and `setup.cfg` in the repository
outside the directories the scan skips. The program has to be the FIRST element
of the command, written as a literal or passed through `shutil.which("mytool")`,
or be a whole one-word string command. The edge then reaches as far as an
import would: node narrowing selects the test function that starts the script,
a helper module that starts it taints only the helper functions that do, and a
conftest fixture that starts it selects the tests that request it. A declared
name that is also an unrelated executable on your PATH is followed anyway,
since the worst that costs is one test run that did not need to happen. What is
still refused, and so still under-selects, is under Limitations.

## Quickstart

```bash
git clone https://github.com/andreruizloera/testsniper
cd testsniper
uv sync
uv run bash demo.sh
```

The demo runs in eight parts. Part 1 copies the generated example project (40
modules, 402 tests) to a temp directory, edits one module, and shows the
default, `--aggressive`, and `--safe --list` selections. Part 2 copies the
mixed example project, edits `store/pricing.py`, and shows the same change
narrowed to individual tests by `--nodes` and by the plugin. Part 3 shows the
file that same change reaches only through a conftest fixture. Part 4 changes a
different module in that project, one an autouse fixture reaches, and shows the
whole directory selected with the reason. Part 5 edits the `conftest.py`
itself, once in a fixture body and once in a comment, and shows the first
selecting two tests and the second selecting none. Part 6 edits a test file
itself, once by adding a test and once by editing a helper method inside a
class, and shows one test selected and then two. Part 7 appends a new function
to `store/pricing.py` and shows that it reaches no existing test, since nothing
calls it. Part 8 copies `examples/script_project`, changes what its `greet`
console script prints, and shows the one test that runs `greet` selected and
failing, although it imports nothing from the project. The script checks the
lines this README pastes and exits nonzero if any of them has drifted.

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
whether any name it reads traces back to one of them. "Affected" is decided per
symbol rather than per module: from its own diff for a module in the change
set, and from which of its names read an affected name of something it imports
for a module downstream of one. A module that is both gets the union of the
two, because a name can move for either reason. Usage follows the file's
own definitions, so a helper, a fixture reached through the parameter that
requests it, a `pytest.mark.usefixtures("name")` mark, and a
`self.other_method()` call all propagate.

A fixture defined in a `conftest.py` is a name like any other. When a conftest
that applies to the file is affected by the change, testsniper reads the whole
conftest chain and works out which fixture names the change reaches, resolving
them the way pytest does: the nearest definition of a name wins, and an
override that requests its own name (`def db(db)`) means the definition it
overrode. Those names are then treated exactly like an affected import.

The analysis refuses to narrow a file, and runs all of it, when:

- it is in an `always_run` path, or it sits under a changed `conftest.py`
  whose diff could not be localized to individual fixtures (see below), or it
  is itself a changed test file whose own diff could not be localized either
- an autouse fixture reaches the change, in the file or in an applicable
  conftest, since an autouse fixture runs for tests that never name it
- a `pytest_*` hook in an applicable conftest reaches the change, since hooks
  see every collected item
- module-level code, in the file or in an applicable conftest, uses an affected
  import, since that runs on import and can configure shared state no
  individual test mentions
- an applicable conftest declares `pytest_plugins`, which can register fixtures
  from a module this analysis never reads
- the file or an applicable conftest star-imports an affected module, imports
  dynamically, reads names through `globals()`, `eval`, or `exec`, calls
  `request.getfixturevalue()`, has an unresolvable relative import, or does not
  parse

A module's symbols are read the same way, and the same care applies: every
symbol in it stays affected when its module-level code changed or reads
something affected (that runs on import), when a star import or a dynamic
import moved, when it declares a module-level `__getattr__`, when it is new, or
when either revision does not parse. A module downstream of the change adds
three refusals of its own: an import cycle, which has no dependency order to
resolve symbols in; a dotted name that more than one file is importable as,
which cannot be attributed to either; and an import whose parent package is
affected and not itself readable, since `from a.b import c` runs
`a/__init__.py` and binds no name that stands for it. Each refusal is printed
with the module it applies to.

Anything the analysis did not recognize is kept, not dropped: an item that has
no matching test function in the AST (a doctest, an item from a custom
collector) always runs. Every refusal prints its reason.

Two of those refusals are narrower than they read. A class-level autouse
fixture that reaches the change selects every test in that class and leaves the
rest of the file narrowed. And a test file that defines its own fixture
shadowing an affected conftest fixture keeps that name marked affected: working
out whether the override is clean is possible, over-selecting is safe, and this
takes the safe one.

### How selection follows fixtures

The same fixture names decide which FILES are selected, which is a separate
question and the one an import graph cannot answer. When a `conftest.py` that
applies to a test file is in the change's closure, or is itself one of the
changed files:

- if the change reaches it only through ordinary fixtures, the files that ask
  for one of those fixtures are selected and the rest are not. Asking means
  reading the name anywhere in the file: a test parameter, another fixture's
  parameter, or a `pytest.mark.usefixtures("name")` mark.
- if the change reaches something that runs for every test underneath
  regardless of what any test asks for (an autouse fixture, a `pytest_*` hook,
  module-level code, `pytest_plugins`), the whole subtree is selected. Nothing
  finer would be true.
- if a file cannot be read well enough to tell (it does not parse, or it calls
  `request.getfixturevalue()`), it is selected. Unknown is not "no".
- `--safe` skips the per-file question and takes the whole subtree whenever any
  fixture is affected. `--aggressive` ignores this channel entirely and drops
  confidence to Low, saying which conftest it ignored.

A file selected this way prints `[fixture]` where an imported one prints
`[distance N]`, and node narrowing still applies to it: being selected through
a fixture does not mean every test in the file runs.

### A changed conftest.py

A `conftest.py` in the change set is read the same way, with one extra input:
its content at the revision being compared against, which `git show` supplies.
The fixture graph is built from both versions and the difference is what the
change reaches. A definition counts as changed when its PARSED SYNTAX moved,
so reformatting a fixture or editing a comment inside it selects nothing.
A docstring is not exempt: under `--doctest-modules` pytest collects doctests
out of a `conftest.py`, so a docstring in one can be a test.

Taint spreads from there the way it does from an import. A changed private
helper taints the fixtures that call it; a changed import statement taints
whatever reads the name it binds; a fixture that requests a changed fixture is
changed too. A DELETED fixture is tainted by name rather than by the graph,
since it has no definition left to walk to, and a file that still asks for it
is selected.

The whole subtree is selected, with the reason, when the diff cannot be
localized:

- module-level code changed, or unchanged module-level code reads something
  that did, since it runs on import
- an autouse fixture or a `pytest_*` hook changed, or was deleted
- a star import changed, so what it binds is unknowable
- there is no previous content (a brand new `conftest.py`), the previous
  content does not parse, or the file was deleted
- `select()` was called without a way to read the old content, which is how
  the library behaves when it is used outside a git repository

`--safe` takes the whole subtree whenever any fixture moved, and
`--aggressive` ignores a changed conftest entirely and drops confidence to
Low, both exactly as they do for an affected one.

### Modes

| Mode | Selection | Changed conftest.py | Affected conftest.py | Changed config or non-Python file |
| --- | --- | --- | --- | --- |
| `--safe` | transitive closure, widened to every module in each changed module's package | selects its whole subtree when any fixture moved | selects its whole subtree | selects everything, with the reason printed |
| default | full transitive closure over the reverse import graph | selects the files that request a fixture the diff moved, or the subtree when the diff is not fixture-shaped | selects the files that request an affected fixture, or the subtree when the change is not fixture-shaped | ignored, confidence drops to Low with a pointer to `--safe` |
| `--aggressive` | only tests that import a changed module directly | ignored, confidence drops to Low | ignored, confidence drops to Low | ignored, confidence drops to Low |

A CHANGED conftest is one in your diff. An AFFECTED one is one that imports
something in your diff, directly or transitively, which is the case its
fixtures have to be read for.

A changed TEST file is always selected, in every mode, so it does not appear
in that table. What the mode decides is whether its diff may narrow inside it:
`--safe` runs all of it, and the other two read the diff.

All modes always include `always_run` paths and rank selected tests by
import distance, direct importers first, then the files reached only through a
fixture. Node narrowing is orthogonal: the mode decides which files are
selected, and `--nodes` then narrows inside each of them.

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
Runtime dispatch, data files, and monkeypatching can all cross module
boundaries invisibly; conftest fixtures are followed, but only the ones written
in Python that testsniper can read. Node narrowing
adds a second such layer, since it reads names rather than executing them.
That is what the confidence rating, the refusal rules above, and `--safe`
are for, and why CI should still run the full suite.

## Architecture

```
src/testsniper/
  cli.py       argument parsing and output
  gitio.py     changed files from git (working tree, staged, or vs a ref),
               and a changed file's content at the compared-against revision
  scanner.py   AST scan of every .py file: imports, star/dynamic flags,
               python -m subprocess targets, and declared console scripts
  entrypoints.py  reads a `python -m <module>` target or a program name
               back out of a subprocess command, and refuses everything
               it cannot read literally
  scripts.py   console-script name -> module, read from every
               pyproject.toml and setup.cfg in the repository
  graph.py     reverse import graph and BFS transitive closure
  indexer.py   test file discovery and test function counting
  selector.py  modes, conftest/config triggers, always_run, confidence,
               and the files reached only through a fixture
  usage.py     name-usage primitives: what a piece of syntax reads
  symbols.py   which symbols of a module a change reaches: from its own
               diff, and from what it imports, propagated across the graph
  nodes.py     per-test name-usage analysis inside a selected file,
               including a test file that changed itself
  fixtures.py  which conftest fixtures a change reaches across the chain,
               including a conftest that changed itself, and which test
               files ask for them
  plan.py      the JSON contract carrying a selection into pytest
  plugin.py    pytest plugin: deselect at collection time
  runner.py    pytest invocation on the selected files
```

The pipeline: diff -> changed modules -> reverse import graph (who imports
whom, transitively) -> test files in the closure, ranked by distance, plus the
files that request a fixture the change reaches -> optionally, the test
functions inside them that read an affected import or ask for such a fixture ->
pytest. Every affected module is separately read for the symbols the change
reaches in it, in dependency order so that each one is answered after the
modules it imports, which refines what "an affected import" means without
touching the graph. Graph nodes are file paths, not module names, so name collisions
(every `conftest.py`) can only over-select, never under-select.

`nodes.py` and `fixtures.py` are pure: they take a root, some paths, a set of
affected module names, and for a changed conftest its previous content as a
string, and return a verdict. Neither knows anything about git, pytest, or the
graph that produced the affected set, and both read files
through the same primitives in `usage.py`, so the in-file and cross-file
analyses cannot drift apart on what a name means. The conftest chain is read
once per chain during selection and the verdict is carried on the `Selection`,
so the file-level and node-level answers come from one reading rather than two.
`plugin.py` is the only module that imports pytest, and nothing imports
`plugin.py`.

Two example projects are committed. `examples/fixture_project/` is generated
deterministically by `scripts/gen_fixture.py`: 10 independent import chains of
4 modules each, 10 tests per module, plus a smoke suite wired into
`always_run`. It shows file-level selection at scale, but every test in one of
its files uses the same module, so node narrowing has nothing to remove there.
`examples/mixed_project/` exists for that: one small store whose checkout test
file mixes pricing, shipping, and formatting tests, so a change to
`price_with_tax` reaches 5 of its 13 test functions and none of the shipping
file. Its `tests/conftest.py`
is mixed the same way, with one fixture a pricing change reaches, one it does
not, and one autouse fixture that a receipts change does reach. A third test
file, `tests/test_totals_report.py`, imports nothing a pricing change touches
and is reachable only through that conftest fixture, which is what the import
graph on its own cannot see.

## Limitations

- pytest only. File-level selection is the default; node-level selection
  needs `--nodes` or the plugin.
- Static analysis: dynamic imports and plugin registries are invisible; the
  confidence rating tells you when that matters.
- A subprocess that runs the project is followed in two forms: `python -m
  <module>` with both `-m` and the module name written as string literals, and
  a console script declared in `pyproject.toml` or `setup.cfg`, started by its
  name as the first element of the command. A module or program name held in a
  variable or built with an f-string, any string command other than a single
  word naming a declared script, a script started through a launcher
  (`["uv", "run", "mytool"]`) or by path, and a script declared only in
  `setup.py` are all invisible, and invisible here means under-selection rather
  than over-selection: the tests that exercise your command line will not be
  selected. `--safe` is the answer when that matters, and the launcher and path
  cases are in ROADMAP.md.
- Node narrowing reads names, so it cannot see through `getattr`, string
  dispatch, or a module named only by a string (`pytest.importorskip("x")`).
  It sees `globals`, `eval`, `exec`, `request.getfixturevalue`, star imports of
  the change, and dynamic imports, and refuses to narrow when it finds them,
  but `getattr` is too common in test code to treat as a signal and is
  deliberately ignored.
- Fixtures are followed through `conftest.py` files, but only the ones written
  in Python that testsniper can read. A fixture a plugin registers, or one
  reached through `pytest_plugins`, is not attributable to a test by any amount
  of AST reading; `pytest_plugins` is a refusal, and an installed plugin's
  fixtures are simply invisible.
- **A conftest that reaches the change for every test underneath selects its
  whole subtree.** That is an autouse fixture, a `pytest_*` hook, module-level
  code, or `pytest_plugins`, and it is the correct answer rather than a
  heuristic: those run whether a test asks for them or not. The same holds
  when the conftest is what changed and the diff touched one of those. The cost is that a
  root `conftest.py` with an autouse fixture that touches application code will
  select the entire suite on most changes. Selection says which conftest did it
  and why, so you can see it happening; moving that fixture down the tree, or
  narrowing what it imports, is the fix.
- Selecting a file through a fixture asks whether the name is read anywhere in
  it, not which test reads it. That is deliberate, since the per-test question
  is what `--nodes` answers, but it means a local variable that happens to
  share a conftest fixture's name will select the file. Over-selection, and it
  costs a file rather than a suite.
- A changed `conftest.py` or test file is diffed against one revision: the
  one the run compares against (`HEAD`, or the revision you name). Two edits in
  a row without a commit are one diff, which is correct, but it also means a
  file changed in an earlier, already-committed commit is not in the change set
  at all unless you point testsniper at a revision before it.
- A changed test file is diffed by parsed syntax, so moving a test within its
  file selects nothing, and renaming one selects the new name only. Neither is
  wrong, but neither is what a reader of the text diff would predict.
- Symbol narrowing crosses the import graph, but it gives up on a whole module
  rather than guess when the answer would not be sound: a star import, an
  unresolved relative import, a dynamic import, a module-level `__getattr__`,
  module-level code that reads something affected, an import cycle, two files
  importable under the same dotted name, and a package whose `__init__` is
  affected and runs on the way to a submodule. Every symbol in a module it
  gives up on stays affected. The run names those modules and the reason, so
  the widening is visible rather than silent.
- Symbol narrowing needs the bound name to BE the symbol, which is the
  `from module import name` form. A plain `import package.module` binds the
  module object, and `package.module.name()` is an attribute read this analysis
  does not trace back to a name, so that import keeps the whole module
  affected. Same for `from module import *`.
- A file whose imports reach the change but whose tests never use them is
  dropped entirely. That is the intended behavior and it is the case most
  likely to surprise; `--list` names every selected function so you can check.
- Test counts are counted from the AST, so parametrized tests count once
  per function; the run totals from pytest are exact.
- pytest output is captured and reprinted after the run finishes rather
  than streamed live.
- testsniper must share an environment with the target project's pytest.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Highlights: PyPI release, resolving
`package.module.name()` attribute reads back to a symbol, import graph caching,
and coverage-map hybrid selection.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Development is uv-based:
`uv sync`, `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`.

GitHub topics: `testing`, `pytest`, `developer-tools`, `test-selection`, `ci`.

## License

MIT, see [LICENSE](LICENSE).
