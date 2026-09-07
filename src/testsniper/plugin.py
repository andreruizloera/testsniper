"""pytest plugin: deselect the tests a change cannot reach, at collection time.

The command-line tool hands pytest a list of files. That is as precise as an
argument list can be, because a file is the smallest thing you can name
without knowing what is inside it. This plugin runs inside pytest instead,
after collection, where every test is a real item with a real node ID, so it
can drop individual test functions and keep every parametrized case of the
ones it keeps without guessing any of those names from source.

Two ways in, one deselect path:

    pytest --testsniper                # analyze here, then deselect
    pytest --testsniper-plan plan.json # apply an analysis done elsewhere

The plugin is registered through the ``pytest11`` entry point and is inert
until one of those flags is passed. Deselection happens after collection, so
the modules were imported either way: a change that breaks an import still
fails the run rather than disappearing with the tests that would have caught
it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from testsniper import plan as plan_mod
from testsniper.config import load_config
from testsniper.gitio import GitError, changed_files, file_at_ref, repo_root
from testsniper.nodes import Key, narrow_selection
from testsniper.plan import Plan
from testsniper.scanner import scan_repo
from testsniper.selector import Mode, select

_STASH = pytest.StashKey["_Report"]()


@dataclass
class _Report:
    """What the plugin did, kept for the end-of-run summary."""

    plan: Plan
    kept: int = 0
    deselected: int = 0
    unindexed: int = 0
    per_file: dict[str, tuple[int, int]] = field(default_factory=dict)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("testsniper", "run only the tests a change can affect")
    group.addoption(
        "--testsniper",
        action="store_true",
        default=False,
        help="deselect tests that cannot reach the working-tree change",
    )
    group.addoption(
        "--testsniper-ref",
        action="store",
        default=None,
        metavar="REF",
        help="git revision to diff against (implies --testsniper; default HEAD)",
    )
    group.addoption(
        "--testsniper-staged",
        action="store_true",
        default=False,
        help="select from staged changes instead of the working tree (implies --testsniper)",
    )
    group.addoption(
        "--testsniper-mode",
        action="store",
        default="default",
        choices=("safe", "default", "aggressive"),
        help="selection mode, matching the testsniper command (default: default)",
    )
    group.addoption(
        "--testsniper-plan",
        action="store",
        default=None,
        metavar="PATH",
        help="apply a plan written by the testsniper command instead of analyzing here",
    )


def _wants_analysis(config: pytest.Config) -> bool:
    return bool(
        config.getoption("--testsniper")
        or config.getoption("--testsniper-ref")
        or config.getoption("--testsniper-staged")
    )


def _build_plan(config: pytest.Config) -> Plan:
    """Run the full analysis from inside pytest."""
    ref = config.getoption("--testsniper-ref")
    staged = config.getoption("--testsniper-staged")
    mode: Mode = config.getoption("--testsniper-mode")
    start = Path(config.invocation_params.dir)
    try:
        root = repo_root(start)
        changed = changed_files(root, ref=ref, staged=staged)
    except GitError as exc:
        raise pytest.UsageError(f"testsniper: {exc}") from exc

    infos = scan_repo(root)
    # The revision the change is measured against, and therefore where a
    # changed file's previous content has to come from. Without this the
    # plugin would answer a changed conftest.py by running its whole subtree,
    # which is the fallback for a caller that cannot read the old content,
    # not the answer the command gives.
    base = ref or "HEAD"
    selection = select(
        root,
        changed,
        mode,
        load_config(root),
        infos,
        old_source=lambda relpath: file_at_ref(root, relpath, base),
    )
    nodes = narrow_selection(root, selection, infos)
    if staged:
        source = "staged changes"
    else:
        source = f"working tree vs {ref}" if ref else "working tree vs HEAD"
    summary = f"{len(selection.changed)} changed file(s), {source}"
    if not selection.changed:
        summary = f"no changes detected ({source})"
    return plan_mod.build_plan(root, selection, nodes, summary=summary)


def _load_plan(config: pytest.Config) -> Plan:
    path = Path(config.getoption("--testsniper-plan"))
    try:
        return plan_mod.read(path)
    except plan_mod.PlanError as exc:
        raise pytest.UsageError(f"testsniper: {exc}") from exc


def item_key(item: pytest.Item) -> Key:
    """The (class path, function name) key of a collected item.

    Derived from the node ID, so nested classes and parametrization are
    handled exactly as pytest reports them. The parametrization suffix is
    dropped: selecting a function selects all of its cases.
    """
    parts = item.nodeid.split("::")
    if len(parts) < 2:
        return ("", item.name.split("[", 1)[0])
    name = parts[-1].split("[", 1)[0]
    return ("::".join(parts[1:-1]), name)


def item_relpath(item: pytest.Item, root: Path) -> str | None:
    """Repository-relative path of an item's file, or None if outside it."""
    path = getattr(item, "path", None)
    if path is None:
        return None
    try:
        return Path(str(path)).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def pytest_report_header(config: pytest.Config) -> str | None:
    if config.getoption("--testsniper-plan"):
        return f"testsniper: applying plan {config.getoption('--testsniper-plan')}"
    if not _wants_analysis(config):
        return None
    mode = config.getoption("--testsniper-mode")
    if config.getoption("--testsniper-staged"):
        source = "staged changes"
    else:
        ref = config.getoption("--testsniper-ref")
        source = f"working tree vs {ref}" if ref else "working tree vs HEAD"
    return f"testsniper: {mode} mode, {source}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--testsniper-plan"):
        if _wants_analysis(config):
            raise pytest.UsageError(
                "testsniper: --testsniper-plan cannot be combined with --testsniper"
            )
        plan = _load_plan(config)
    elif _wants_analysis(config):
        plan = _build_plan(config)
    else:
        return

    root = Path(plan.root)
    report = _Report(plan=plan)
    kept: list[pytest.Item] = []
    dropped: list[pytest.Item] = []

    for item in items:
        if plan.select_all:
            kept.append(item)
            continue
        rel = item_relpath(item, root)
        if rel is None or rel not in plan.indexed:
            # Not a file testsniper looked at, so not a file it may judge.
            # A path outside the repository is not worth reporting; a path
            # inside it that never entered the index is.
            if rel is not None:
                report.unindexed += 1
            kept.append(item)
            continue
        if plan.verdict(rel, item_key(item)):
            kept.append(item)
            hit, miss = report.per_file.get(rel, (0, 0))
            report.per_file[rel] = (hit + 1, miss)
        else:
            dropped.append(item)
            hit, miss = report.per_file.get(rel, (0, 0))
            report.per_file[rel] = (hit, miss + 1)

    report.kept = len(kept)
    report.deselected = len(dropped)
    config.stash[_STASH] = report

    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    report = terminalreporter.config.stash.get(_STASH, None)
    if report is None:
        return
    total = report.kept + report.deselected
    write = terminalreporter.write_line
    terminalreporter.write_sep("-", "testsniper")
    if report.plan.summary:
        write(report.plan.summary)
    write(f"selected {report.kept} of {total} collected tests")
    for rel, (hit, miss) in sorted(report.per_file.items()):
        nodes = report.plan.files.get(rel)
        if hit == 0:
            continue
        if nodes is not None and nodes.narrowed and miss:
            write(f"  {rel}: {hit} of {hit + miss}, {nodes.reason}")
        elif nodes is not None and not nodes.narrowed:
            write(f"  {rel}: all {hit}, not narrowed ({nodes.reason})")
    if report.unindexed:
        write(f"kept {report.unindexed} test(s) in files testsniper did not index")
    write(f"selection confidence: {report.plan.confidence}")
    for reason in report.plan.confidence_reasons:
        write(f"  - {reason}")
