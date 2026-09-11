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
the tests that read them. The items below are what none of that does yet.

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
- Decide what to do about `if __name__ == "__main__":`. It is module-level
  code, so a guard body whose call graph reaches the change makes the whole
  module unnarrowable, and running testsniper on testsniper shows it costing
  exactly that on `cli.py` and `__main__.py`. The body does not run on import,
  which is an argument for skipping it. What stops that from being obviously
  right is that a test which invokes the module as a SUBPROCESS does run it,
  and this repository's own CLI tests are that shape, so skipping it would
  trade a safe over-selection for an under-selection in the case most likely
  to be affected. Needs a way to see a subprocess invocation, or a decision
  that this over-selection is the one to keep.
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
