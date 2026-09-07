"""Test selection: turn a set of changed files into a ranked test list."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from testsniper.config import Config
from testsniper.fixtures import FixtureVerdict, analyze_conftests, conftests_for, file_requests
from testsniper.graph import build_reverse_graph, importers_of, reverse_closure
from testsniper.indexer import count_tests_in_file, index_tests, is_test_file, path_is_under
from testsniper.scanner import ModuleInfo, module_name, scan_repo

Mode = Literal["safe", "default", "aggressive"]

PYTEST_CONFIG_FILES: frozenset[str] = frozenset(
    {"pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"}
)

_LEVELS = {"High": 0, "Medium": 1, "Low": 2}


class OldSource(Protocol):
    """The previous content of a changed file, or None if there is none."""

    def __call__(self, relpath: str) -> str | None: ...


class AddTest(Protocol):
    """The one way a run records a selected test file."""

    def __call__(
        self,
        relpath: str,
        distance: int | None,
        reason: str,
        *,
        whole: str | None = None,
        via_fixture: bool = False,
    ) -> None: ...


@dataclass
class SelectedTest:
    """One selected test file with why it was picked."""

    relpath: str
    distance: int | None
    reason: str
    # Why node narrowing may not remove tests from this file, when it may not.
    # Set when a reason to select it is not something per-test name usage can
    # refine: an always_run path, a conftest whose diff could not be localized
    # to individual fixtures, or a conftest that reaches the change for every
    # test underneath. Kept separately from ``reason`` because a file can be
    # selected for one reason and run whole for another.
    whole_file: str | None = None
    # Selected through a conftest fixture rather than an import. Distance is
    # None for these, the same as always_run, but they are not the same thing
    # and the output must not call them one.
    via_fixture: bool = False

    @property
    def narrowable(self) -> bool:
        """Whether node narrowing may drop any of this file's tests."""
        return self.whole_file is None

    def sort_key(self) -> tuple[int, int, str]:
        return (self.distance is None, self.distance or 0, self.relpath)

    @property
    def channel(self) -> str:
        """How the change reaches this file, for one word of output."""
        if self.distance is not None:
            return f"distance {self.distance}"
        return "fixture" if self.via_fixture else "always"


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
    # Everything downstream of the change: the files in the reverse-import
    # closure, and the dotted names they are importable as (plus the names of
    # deleted modules, which have no file left to name them). Node-level
    # narrowing needs this to tell an affected import from an innocent one.
    affected_files: set[str] = field(default_factory=set)
    affected_modules: set[str] = field(default_factory=set)
    # Every test file that was considered, selected or not. A test in a file
    # that never entered the index was never judged, so it must not be dropped.
    indexed: list[str] = field(default_factory=list)
    # Conftest chain -> what the change reaches through it. Filled while
    # selecting, and reused by node narrowing so the two cannot disagree
    # about which fixtures are affected.
    fixture_verdicts: dict[tuple[str, ...], FixtureVerdict] = field(default_factory=dict)
    # Changed test file -> its content at the revision compared against, or
    # None when that revision does not have it. Presence in this map is what
    # says a changed test file may be narrowed by its own diff; absence keeps
    # the older answer, which is to run all of it.
    changed_test_sources: dict[str, str | None] = field(default_factory=dict)

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
    old_source: OldSource | None = None,
) -> Selection:
    """Select the test files affected by the changed files.

    ``old_source`` returns the previous content of a changed file, or None
    when the revision being compared against does not have it. It is the only
    thing here that knows a revision exists; without it a changed
    ``conftest.py`` cannot be diffed and falls back to its whole subtree.
    """
    if infos is None:
        infos = scan_repo(root)
    test_rels = index_tests(root, infos, config)
    test_set = set(test_rels)
    counts = {rel: count_tests_in_file(root, rel) for rel in test_rels}

    changed = sorted({str(PurePosixPath(c)) for c in changed})
    sel = Selection(changed=changed)
    sel.total_test_files = len(test_rels)
    sel.total_tests = sum(counts.values())
    sel.indexed = list(test_rels)
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

    def add(
        relpath: str,
        distance: int | None,
        reason: str,
        *,
        whole: str | None = None,
        via_fixture: bool = False,
    ) -> None:
        existing = picked.get(relpath)
        if existing is None or _better(distance, existing.distance):
            picked[relpath] = SelectedTest(relpath, distance, reason, via_fixture=via_fixture)
            if existing is not None:
                picked[relpath].whole_file = existing.whole_file
        # One reason to run a file whole outranks any number of reasons to
        # narrow it, whichever of them won the right to explain the choice.
        if whole is not None and picked[relpath].whole_file is None:
            picked[relpath].whole_file = whole

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
    sel.affected_files = set(dist)
    sel.affected_modules = {infos[rel].module for rel in dist if rel in infos}
    sel.affected_modules |= {module_name(root, Path(rel)) for rel in deleted}
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

    # A changed conftest whose previous content can be read is analyzed the
    # way an affected one is, below. One that cannot be read at all (it is not
    # in the scan, so it was deleted) keeps the old rule: run the subtree.
    old_sources: dict[str, str | None] = {}
    if conftests and mode != "aggressive":
        for conftest in conftests:
            if conftest in infos and old_source is not None:
                old_sources[conftest] = old_source(conftest)
            else:
                subtree = str(PurePosixPath(conftest).parent)
                reason = f"under changed {conftest}"
                for rel in test_rels:
                    if path_is_under(rel, subtree):
                        add(rel, None, reason, whole=reason)
                sel.notes.append(f"{conftest} changed; selecting its whole subtree")
    # A changed TEST file is read through its own diff the same way, which is
    # a node-level answer: the file is selected either way, and the diff says
    # which of its tests moved. --safe keeps the older answer and runs all of
    # it, exactly as it takes a changed conftest's whole subtree.
    if mode != "safe" and old_source is not None:
        for rel in changed_modules:
            if rel in test_set and rel in infos:
                sel.changed_test_sources[rel] = old_source(rel)

    if conftests and mode == "aggressive":
        sel.degrade(
            "Low",
            "changed conftest.py ignored in aggressive mode; its whole subtree may be affected",
        )

    fixture_reached = _select_through_fixtures(
        root, sel, infos, test_rels, mode, picked, add, old_sources
    )

    for path in config.always_run:
        reason = f"always_run ({path})"
        for rel in test_rels:
            if path_is_under(rel, path):
                add(rel, None, reason, whole=reason)

    for rel in changed_modules:
        if rel in test_set or rel in deleted:
            continue
        reach = reverse_closure(reverse, {rel: 0}) if rel in infos else {}
        if any(r in test_set or r in fixture_reached for r in reach):
            continue
        sel.unreached.append(rel)

    sel.tests = sorted(picked.values(), key=SelectedTest.sort_key)
    sel.selected_tests = sum(counts.get(t.relpath, 0) for t in sel.tests)
    _score_confidence(sel, infos, mode, config_changes, other_changes)
    return sel


def _select_through_fixtures(
    root: Path,
    sel: Selection,
    infos: dict[str, ModuleInfo],
    test_rels: list[str],
    mode: Mode,
    picked: dict[str, SelectedTest],
    add: AddTest,
    old_sources: dict[str, str | None],
) -> set[str]:
    """Select test files that reach the change only through a conftest fixture.

    The import graph cannot see these. A test file that imports nothing
    affected is not in the closure at all, so node narrowing never sees it
    either: narrowing only ever removes tests from a file already selected.
    What connects it to the change is a fixture name, resolved in a
    ``conftest.py`` the file never mentions.

    So the conftest chain decides. When the change reaches a fixture, the
    files that ask for that fixture are selected, and nothing else is. When it
    reaches something that runs for every test underneath regardless of what
    any test asks for (an autouse fixture, a hook, module-level code, or
    anything unreadable), the whole subtree is selected, because that is what
    the change actually reaches. ``--safe`` skips the per-file question and
    takes the subtree whenever any fixture is affected.

    Returns the affected conftests that carried the change to at least one
    test file, so a changed module reached only that way is not reported as
    reaching no test.
    """
    known = {rel for rel in infos if PurePosixPath(rel).name == "conftest.py"}
    in_play = sel.affected_files | set(old_sources)
    affected_conftests = sorted(c for c in known if c in in_play)
    if not affected_conftests:
        return set()
    if mode == "aggressive":
        sel.degrade(
            "Low",
            f"affected conftest.py fixtures ignored in aggressive mode"
            f" ({', '.join(affected_conftests[:3])}); tests can reach the change through them",
        )
        return set()

    reached: set[str] = set()
    notes: dict[tuple[str, ...], str] = {}
    for rel in test_rels:
        chain = tuple(c for c in conftests_for(rel) if c in known)
        hit = [c for c in chain if c in in_play]
        if not hit:
            continue
        if chain not in sel.fixture_verdicts:
            sel.fixture_verdicts[chain] = analyze_conftests(
                root,
                list(chain),
                sel.affected_modules,
                infos,
                old_sources={c: old_sources[c] for c in chain if c in old_sources},
            )
        verdict = sel.fixture_verdicts[chain]
        nearest = hit[-1]
        # The nearest conftest that carried the change either changed itself
        # or reads something that did, and the reason should say which.
        kind = "changed" if nearest in old_sources else "affected"
        was_picked = rel in picked

        if verdict.block is not None:
            add(rel, None, verdict.block, whole=verdict.block, via_fixture=True)
            reached.update(hit)
            if not was_picked:
                notes[chain] = f"{verdict.block}, so every test it applies to is selected"
            continue
        if not verdict.tainted:
            continue

        names = ", ".join(sorted(verdict.tainted))
        if mode == "safe":
            add(
                rel,
                None,
                f"under {kind} {nearest}, whose fixtures reach the change",
                via_fixture=True,
            )
            reached.update(hit)
            if not was_picked:
                notes[chain] = (
                    f"{nearest} is {kind} through {names}; safe mode selects its whole subtree"
                )
            continue

        module = infos[rel].module if rel in infos else rel
        request = file_requests(root, rel, module, verdict.tainted)
        if not request.requested:
            continue
        reached.update(hit)
        if request.unreadable:
            add(
                rel,
                None,
                f"{request.unreadable}, so it may request a {kind} fixture",
                via_fixture=True,
            )
        else:
            asked = ", ".join(sorted(request.requested))
            add(
                rel,
                None,
                f"requests {kind} fixture {asked} from {nearest}",
                via_fixture=True,
            )
        if not was_picked:
            notes[chain] = (
                f"{nearest} is {kind} through {names};"
                " selecting the tests that request those fixtures"
            )

    sel.notes.extend(notes[chain] for chain in sorted(notes))
    return reached


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
