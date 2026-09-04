"""Test selection: turn a set of changed files into a ranked test list."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from testsniper.config import Config
from testsniper.graph import build_reverse_graph, importers_of, reverse_closure
from testsniper.indexer import count_tests_in_file, index_tests, is_test_file, path_is_under
from testsniper.scanner import ModuleInfo, module_name, scan_repo

Mode = Literal["safe", "default", "aggressive"]

PYTEST_CONFIG_FILES: frozenset[str] = frozenset(
    {"pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"}
)

_LEVELS = {"High": 0, "Medium": 1, "Low": 2}


@dataclass
class SelectedTest:
    """One selected test file with why it was picked."""

    relpath: str
    distance: int | None
    reason: str

    def sort_key(self) -> tuple[int, int, str]:
        return (self.distance is None, self.distance or 0, self.relpath)


@dataclass
class Selection:
    """Full result of a selection run."""

    changed: list[str]
    tests: list[SelectedTest] = field(default_factory=list)
    total_test_files: int = 0
    total_tests: int = 0
    selected_tests: int = 0
    select_all: bool = False
    select_all_reason: str | None = None
    unreached: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confidence: str = "High"
    confidence_reasons: list[str] = field(default_factory=list)

    def degrade(self, level: str, reason: str) -> None:
        if _LEVELS[level] > _LEVELS[self.confidence]:
            self.confidence = level
        self.confidence_reasons.append(reason)


def select(
    root: Path,
    changed: list[str],
    mode: Mode,
    config: Config,
    infos: dict[str, ModuleInfo] | None = None,
) -> Selection:
    """Select the test files affected by the changed files."""
    if infos is None:
        infos = scan_repo(root)
    test_rels = index_tests(root, infos, config)
    test_set = set(test_rels)
    counts = {rel: count_tests_in_file(root, rel) for rel in test_rels}

    changed = sorted({str(PurePosixPath(c)) for c in changed})
    sel = Selection(changed=changed)
    sel.total_test_files = len(test_rels)
    sel.total_tests = sum(counts.values())
    if not changed:
        return sel

    changed_py = [c for c in changed if c.endswith(".py")]
    conftests = [c for c in changed_py if PurePosixPath(c).name == "conftest.py"]
    changed_modules = [c for c in changed_py if PurePosixPath(c).name != "conftest.py"]
    non_py = [c for c in changed if not c.endswith(".py")]
    config_changes = [c for c in non_py if PurePosixPath(c).name in PYTEST_CONFIG_FILES]
    other_changes = [c for c in non_py if c not in config_changes]

    if mode == "safe" and non_py:
        trigger = (config_changes or other_changes)[0]
        kind = "pytest configuration" if config_changes else "a non-Python file"
        sel.select_all = True
        sel.select_all_reason = f"{kind} changed ({trigger}); import analysis cannot scope it"
        sel.tests = [SelectedTest(rel, None, "safe: select everything") for rel in test_rels]
        sel.selected_tests = sel.total_tests
        sel.confidence_reasons.append("everything is selected, nothing can be missed")
        return sel

    reverse = build_reverse_graph(infos)
    picked: dict[str, SelectedTest] = {}

    def add(relpath: str, distance: int | None, reason: str) -> None:
        existing = picked.get(relpath)
        if existing is None or _better(distance, existing.distance):
            picked[relpath] = SelectedTest(relpath, distance, reason)

    seeds: dict[str, int] = {}
    deleted: list[str] = []
    for rel in changed_modules:
        if rel in infos:
            seeds[rel] = 0
        else:
            deleted.append(rel)

    if mode == "safe":
        for rel in list(seeds):
            parent = str(PurePosixPath(rel).parent)
            for sibling in infos:
                if (
                    str(PurePosixPath(sibling).parent) == parent
                    and not is_test_file(sibling)
                    and PurePosixPath(sibling).name != "conftest.py"
                ):
                    seeds.setdefault(sibling, 0)
        if len(seeds) > len(changed_modules):
            sel.notes.append("safe mode widened the change set to whole packages")

    for rel in deleted:
        dotted = module_name(root, Path(rel))
        for importer in importers_of(infos, dotted):
            seeds[importer] = min(seeds.get(importer, 1), 1)
        sel.notes.append(f"{rel} was deleted; selecting tests for its importers")

    dist = reverse_closure(reverse, seeds)
    for rel, d in dist.items():
        if rel not in test_set:
            continue
        if mode == "aggressive" and d > 1:
            continue
        if d == 0:
            add(rel, 0, "changed test file")
        elif d == 1:
            add(rel, 1, "imports a changed module")
        else:
            add(rel, d, f"imports it transitively (distance {d})")

    if conftests:
        if mode == "aggressive":
            sel.degrade(
                "Low",
                "changed conftest.py ignored in aggressive mode; its whole subtree may be affected",
            )
        else:
            for conftest in conftests:
                subtree = str(PurePosixPath(conftest).parent)
                for rel in test_rels:
                    if path_is_under(rel, subtree):
                        add(rel, None, f"under changed {conftest}")
                sel.notes.append(f"{conftest} changed; selecting its whole subtree")

    for path in config.always_run:
        for rel in test_rels:
            if path_is_under(rel, path):
                add(rel, None, f"always_run ({path})")

    for rel in changed_modules:
        if rel in test_set or rel in deleted:
            continue
        reach = reverse_closure(reverse, {rel: 0}) if rel in infos else {}
        if not any(r in test_set for r in reach):
            sel.unreached.append(rel)

    sel.tests = sorted(picked.values(), key=SelectedTest.sort_key)
    sel.selected_tests = sum(counts.get(t.relpath, 0) for t in sel.tests)
    _score_confidence(sel, infos, mode, config_changes, other_changes)
    return sel


def _better(new: int | None, old: int | None) -> bool:
    if old is None:
        return new is not None
    return new is not None and new < old


def _score_confidence(
    sel: Selection,
    infos: dict[str, ModuleInfo],
    mode: Mode,
    config_changes: list[str],
    other_changes: list[str],
) -> None:
    parse_errors = sorted(rel for rel, info in infos.items() if info.parse_error)
    if parse_errors:
        shown = ", ".join(parse_errors[:3])
        sel.degrade("Low", f"could not parse {len(parse_errors)} file(s) ({shown})")
    if config_changes:
        sel.degrade(
            "Low",
            f"pytest configuration changed ({', '.join(config_changes)}) but was not analyzed;"
            " use --safe to run everything",
        )
    if other_changes:
        shown = ", ".join(other_changes[:3])
        sel.degrade(
            "Low",
            f"non-Python files changed ({shown}) and cannot be traced by imports;"
            " use --safe to run everything",
        )
    star = sorted(rel for rel, info in infos.items() if info.star_imports)
    if star:
        sel.degrade(
            "Medium", f"star imports in {len(star)} file(s) (e.g. {star[0]}) can hide dependencies"
        )
    dynamic = sorted(rel for rel, info in infos.items() if info.dynamic_import)
    if dynamic:
        sel.degrade(
            "Medium",
            f"dynamic imports in {len(dynamic)} file(s) (e.g. {dynamic[0]})"
            " cannot be traced statically",
        )
    unresolved = sorted(rel for rel, info in infos.items() if info.unresolved_relative)
    if unresolved:
        sel.degrade("Medium", f"unresolved relative imports in {len(unresolved)} file(s)")
    if sel.unreached:
        shown = ", ".join(sel.unreached[:5])
        sel.degrade("Medium", f"no test imports these changed modules: {shown}")
    if mode == "aggressive":
        sel.degrade("Medium", "aggressive mode skips transitive importers")
