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
- Narrow on the changed symbol, not just the changed module: a test that uses
  only `pricing.line_total` does not need to run when only
  `pricing.price_with_tax` changed.
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
