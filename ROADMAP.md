# Roadmap

Concrete future work. Everything listed below is unimplemented; the one
place a shipped feature is named, it is named as shipped and only to say
what it stops short of.

## Near term

- PyPI release so `pip install testsniper` works without git.
- Stream pytest output live instead of capturing and reprinting it.
- `--dry-run-command` flag that prints the exact pytest invocation for
  copy-pasting into other tools.
- Read `testpaths` from `setup.cfg` and `tox.ini` in addition to
  `pyproject.toml` and `pytest.ini`.
- `--json` output for editor and CI integrations.
- `--write-plan PATH` so a selection computed on one machine can be applied
  by `pytest --testsniper-plan` on another (the plan records an absolute
  repository root today, so this needs a relocation rule first).

## Selection quality

Test-node granularity shipped: `--nodes` and the `--testsniper` plugin
select individual test functions. The cross-file fixture graph shipped after
it, and then file-level selection through that graph: a test file that imports
nothing affected and reaches the change only through a conftest fixture is now
selected, and a conftest that reaches the change for every test underneath
selects its subtree. Reading a CHANGED conftest through its own diff shipped
after that: its previous content comes from git, the fixture graph is built
from both versions, and only the fixtures the diff moved select tests. A
changed TEST file is read the same way now, so it no longer runs in full: the
tests its diff moved are selected, and a helper or fixture it moved selects
the tests that read them. Most recently, a `python -m <module>` subprocess is
followed as a dependency, so a command-line end-to-end test that imports none
of the code it exercises is selected when that code changes. The items below
are what none of that does yet.

- Diff a changed conftest or test file against more than one revision, so one
  edited in an earlier commit is read as changed too. Today the comparison is
  against exactly the revision the run diffs against.
- Attribute a changed conftest's diff to individual TESTS rather than to files,
  by asking which fixtures each test function requests. `--nodes` already
  narrows inside a selected file using the same names; what it does not do is
  use them to drop a file whose tests all request something else.
- Fixture awareness for plugin-provided fixtures, which no amount of AST
  reading can attribute to a test. `pytest_plugins` is a refusal today; an
  installed plugin's fixtures are invisible.
- Decide whether a test file's own fixture cleanly overrides an affected
  conftest fixture of the same name. Today the name stays marked affected,
  which over-selects that file's tests.
- Match a renamed test to the one it was renamed from, which the parsed-syntax
  comparison reads as one deleted definition and one added one. A rename that
  also edits the body is not distinguishable from a delete and an add, so this
  needs a similarity rule rather than an exact one.
- Read a changed test file's diff against a changed conftest's at the same
  time. Today each is answered on its own and the two sets are unioned, which
  can only over-select, but a test dropped by one and kept by the other is
  kept.
- Widen the propagation's refusals back down, one at a time and each with a
  case that proves it is safe. Carrying symbol narrowing past the first import
  hop shipped; what it gives up on is now the interesting part, and three of
  the refusals look reducible. An import cycle could be resolved by iterating
  the whole strongly-connected component to a fixed point instead of refusing
  it. A dotted name that two files share could be answered by keying the
  symbol map on the file rather than the module, which is what the import
  graph already does for exactly this reason. And a module-level statement
  that reads something affected currently blocks the whole module, where only
  the names that statement binds are really at risk.
- Follow a console script started through a launcher or by path, which is
  the part of subprocess following still refused. Resolving a script NAME to
  its module shipped: `subprocess.run(["mytool", "--flag"])` is followed
  through `[project.scripts]`, `[project.gui-scripts]`,
  `[tool.poetry.scripts]` and `setup.cfg`, and a declared name that collides
  with a real executable on PATH is followed anyway, because the cost of that
  is one unnecessary test run. Still invisible, and still an UNDER-selection:
  a launcher that puts the script in a later position (`["uv", "run",
  "mytool"]`, `["pipx", "run", "mytool"]`, `["hatch", "run", "mytool"]`); a
  script started by path (`str(venv / "bin" / "mytool")`,
  `sysconfig.get_path("scripts")`); and a script declared only in `setup.py`,
  which is code. The launcher case wants a short list of launchers and the
  position each one puts the program in, not a reading of every position,
  which would bind a test to every declared name it merely passes as an
  argument.
- Read a `-m` target that is not a literal: a module name held in a variable,
  built with an f-string, or assembled from a constant defined elsewhere in
  the file. Constant folding within one module would cover most real cases.
  Refused today rather than guessed at.
- Decide what to do about `if __name__ == "__main__":`, which is still open,
  but for different reasons than this file gave before subprocess following
  shipped. The guard body is module-level code, so a guard whose call graph
  reaches the change makes the whole module unnarrowable, and running
  testsniper on testsniper still shows it costing exactly that on `cli.py` and
  `__main__.py`. What this file previously said was that skipping the body
  would trade a safe over-selection for an under-selection, "and this
  repository's own CLI tests are that shape". **Measured, that was wrong in
  both halves.** `tests/test_cli.py` calls `main([...])` IN PROCESS, so
  `cli.py`'s guard never runs for it; the tests that do start a process live in
  three other files and reach `cli.main` through `__main__.py`, whose guard is
  the one that runs. And the over-selection was not protecting them: with the
  guard honoured and both modules fully affected, all 22 of those tests were
  still missed, because what was missing was the edge and not a symbol. So the
  real question left is narrower: whether a guard body should be analyzed as
  the entry point of the module that `python -m` executes, which would let
  `__main__.py` narrow on the symbol the guard actually calls instead of
  blocking.
- Resolve `package.module.name()` attribute reads back to a symbol, so a plain
  `import package.module` can be narrowed the way `from package.module import
  name` now is. Today the attribute chain is not tracked and that import keeps
  the whole module affected.
- Follow `self.attr` set in a fixture or `setup_method`, which the class-level
  propagation currently only approximates.
- Hybrid mode: consume a coverage map (pytest-cov contexts) when one
  exists and fall back to the import graph when it does not.
- Namespace package (PEP 420) support; today a missing `__init__.py`
  stops the module name walk.
- Track `importlib.import_module` calls with literal string arguments
  instead of just degrading confidence.

## Performance

- Cache the import graph keyed by file content hashes so repeated runs
  only rescan changed files.
- Optional pytest-xdist integration to parallelize the selected subset.

## Workflow

- `--watch` mode: rerun the selection whenever a file changes.
- A ready-made pre-push git hook and a GitHub Actions example that runs
  the sniped subset on pull requests and the full suite on main.
