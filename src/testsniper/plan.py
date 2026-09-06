"""The selection plan: what the CLI hands the pytest plugin.

Node-level deselection has to happen inside pytest, at collection time, where
the real collected items are known. The analysis, though, wants to run once,
in the CLI, next to the git diff it was computed from. A plan is the small
JSON document that carries one across to the other: which test files survive,
and for each of them either "run all of it" or the exact set of test
functions that reach the change.

A file absent from the plan is a file with no selected tests. That is the
whole contract, and it is versioned so a stale plan is rejected rather than
silently misread.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from testsniper.nodes import FileNodes, Key
from testsniper.selector import Selection

PLAN_VERSION = 1


class PlanError(Exception):
    """A plan file could not be read as a plan."""


@dataclass
class Plan:
    """A resolved selection, ready to be applied to collected items."""

    root: str
    select_all: bool = False
    files: dict[str, FileNodes] = field(default_factory=dict)
    # Every test file the analysis considered. A collected test outside this
    # set was never judged and is therefore never deselected.
    indexed: set[str] = field(default_factory=set)
    confidence: str = "High"
    confidence_reasons: list[str] = field(default_factory=list)
    summary: str = ""

    def verdict(self, relpath: str, key: Key) -> bool:
        """Whether one collected test should run."""
        if self.select_all:
            return True
        nodes = self.files.get(relpath)
        if nodes is None:
            return False
        return nodes.keeps(key)


def build_plan(
    root: Path,
    selection: Selection,
    nodes: dict[str, FileNodes],
    summary: str = "",
) -> Plan:
    """Assemble a plan from a selection and its node narrowing."""
    return Plan(
        root=str(root.resolve()),
        select_all=selection.select_all,
        files=dict(nodes),
        indexed=set(selection.indexed),
        confidence=selection.confidence,
        confidence_reasons=list(selection.confidence_reasons),
        summary=summary,
    )


def dumps(plan: Plan) -> str:
    """Serialize a plan. Keys are sorted so the output is reproducible."""
    files = {
        rel: {
            "narrowed": nodes.narrowed,
            "reason": nodes.reason,
            "selected": sorted([cls, name] for cls, name in nodes.selected),
            "known": sorted([cls, name] for cls, name in nodes.known),
        }
        for rel, nodes in sorted(plan.files.items())
    }
    return json.dumps(
        {
            "version": PLAN_VERSION,
            "root": plan.root,
            "select_all": plan.select_all,
            "indexed": sorted(plan.indexed),
            "confidence": plan.confidence,
            "confidence_reasons": plan.confidence_reasons,
            "summary": plan.summary,
            "files": files,
        },
        indent=2,
    )


def loads(text: str) -> Plan:
    """Parse a plan, raising PlanError on anything that is not one."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("plan is not a JSON object")
    version = data.get("version")
    if version != PLAN_VERSION:
        raise PlanError(f"plan version {version!r} is not supported (expected {PLAN_VERSION})")
    root = data.get("root")
    if not isinstance(root, str):
        raise PlanError("plan has no root path")

    files: dict[str, FileNodes] = {}
    raw_files = data.get("files")
    if not isinstance(raw_files, dict):
        raise PlanError("plan has no files map")
    for rel, entry in raw_files.items():
        if not isinstance(entry, dict):
            raise PlanError(f"plan entry for {rel} is not an object")
        files[rel] = FileNodes(
            relpath=rel,
            narrowed=bool(entry.get("narrowed")),
            reason=str(entry.get("reason", "")),
            selected={(k[0], k[1]) for k in entry.get("selected", [])},
            known={(k[0], k[1]) for k in entry.get("known", [])},
        )

    raw_indexed = data.get("indexed", [])
    if not isinstance(raw_indexed, list):
        raise PlanError("plan indexed list is not a list")

    return Plan(
        root=root,
        select_all=bool(data.get("select_all")),
        files=files,
        indexed={str(rel) for rel in raw_indexed},
        confidence=str(data.get("confidence", "High")),
        confidence_reasons=list(data.get("confidence_reasons", [])),
        summary=str(data.get("summary", "")),
    )


def write(path: Path, plan: Plan) -> None:
    path.write_text(dumps(plan), encoding="utf-8")


def read(path: Path) -> Plan:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlanError(f"could not read plan {path}: {exc}") from exc
    return loads(text)
