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
selects its subtree. The items below are what none of that does yet.

- Read a CHANGED conftest.py the way an affected one is read. Today a changed
  conftest selects its whole subtree and switches narrowing off for it, because
  the graph can only read its fixtures at their new content and cannot tell
  which of them the diff actually touched. Reading the old content out of git
  and diffing the fixture graphs would narrow it to the fixtures that moved.
- Fixture awareness for plugin-provided fixtures, which no amount of AST
  reading can attribute to a test. `pytest_plugins` is a refusal today; an
  installed plugin's fixtures are invisible.
- Decide whether a test file's own fixture cleanly overrides an affected
  conftest fixture of the same name. Today the name stays marked affected,
  which over-selects that file's tests.
- Diff-hunk narrowing for a changed test file. Today a changed test file runs
  in full; the diff says which functions moved.
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
