"""Command-line interface for testsniper."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from testsniper import __version__
from testsniper import plan as plan_mod
from testsniper.config import load_config
from testsniper.gitio import GitError, changed_files, repo_root
from testsniper.nodes import FileNodes, narrow_selection
from testsniper.runner import run_pytest
from testsniper.scanner import scan_repo
from testsniper.selector import Mode, Selection, select


def _fmt(n: int) -> str:
    return f"{n:,}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testsniper",
        description="Run the tests your code change can actually affect.",
    )
    parser.add_argument(
        "ref",
        nargs="?",
        default=None,
        help="git revision to diff the working tree against (default: HEAD)",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="select from staged changes (git diff --cached) instead of the working tree",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--safe",
        action="store_true",
        help="over-select: widen to whole packages, and run everything on config changes",
    )
    mode_group.add_argument(
        "--aggressive",
        action="store_true",
        help="under-select: only tests that import a changed module directly",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the selection and exit without running pytest",
    )
    parser.add_argument(
        "--nodes",
        action="store_true",
        help="narrow to individual test functions, not whole files (uses the pytest plugin)",
    )
    parser.add_argument("--version", action="version", version=f"testsniper {__version__}")
    return parser


def _print_confidence(sel: Selection) -> None:
    print(f"Selection confidence: {sel.confidence}")
    for reason in sel.confidence_reasons:
        print(f"  - {reason}")


def _print_warnings(sel: Selection) -> None:
    for rel in sel.unreached:
        print(f"Warning: no test reaches changed module {rel}")


def _print_list(sel: Selection, nodes: dict[str, FileNodes] | None) -> None:
    would_run = sel.selected_tests
    if nodes is not None:
        would_run -= sum(n.dropped for n in nodes.values())
    print(f"Selected (would run {_fmt(would_run)} of {_fmt(sel.total_tests)} tests):")
    for test in sel.tests:
        where = "always" if test.distance is None else f"distance {test.distance}"
        print(f"  {test.relpath}  [{where}] {test.reason}")
        if nodes is None:
            continue
        file_nodes = nodes.get(test.relpath)
        if file_nodes is None:
            continue
        if not file_nodes.narrowed:
            print(f"    all tests: {file_nodes.reason}")
            continue
        kept = len(file_nodes.selected)
        total = len(file_nodes.known)
        print(f"    {kept} of {total} tests: {file_nodes.reason}")
        for cls, name in sorted(file_nodes.selected):
            print(f"      {cls}::{name}" if cls else f"      {name}")
    _print_warnings(sel)
    _print_confidence(sel)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.staged and args.ref:
        print("error: --staged and an explicit revision cannot be combined", file=sys.stderr)
        return 2

    mode: Mode = "safe" if args.safe else ("aggressive" if args.aggressive else "default")

    try:
        root = repo_root(Path.cwd())
        changed = changed_files(root, ref=args.ref, staged=args.staged)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    config = load_config(root)
    infos = scan_repo(root)
    sel = select(root, changed, mode, config, infos)
    nodes = narrow_selection(root, sel, infos) if args.nodes else None

    if not sel.changed:
        print("No changes detected. Nothing to run.")
        return 0

    print(f"Changed: {', '.join(sel.changed)}")
    for note in sel.notes:
        print(f"Note: {note}")

    if sel.select_all:
        print(f"Selected: all tests ({sel.select_all_reason})")
    elif sel.tests:
        print("Selected: " + ", ".join(t.relpath for t in sel.tests))
    else:
        print("Selected: none")

    if args.list:
        _print_list(sel, nodes)
        return 0

    if not sel.tests:
        print("No tests selected.")
        _print_warnings(sel)
        _print_confidence(sel)
        return 0

    files = [t.relpath for t in sel.tests]
    unselected = sel.total_tests - sel.selected_tests
    if nodes is None:
        print(f"Running {_fmt(sel.selected_tests)} of {_fmt(sel.total_tests)} tests...")
        code, output = run_pytest(root, files)
        skipped = f"Skipped: {_fmt(unselected)} (not selected)"
    else:
        dropped = sum(n.dropped for n in nodes.values())
        print(
            f"Running {_fmt(sel.selected_tests - dropped)} of {_fmt(sel.total_tests)} tests"
            f" ({_fmt(dropped)} more dropped inside the selected files)..."
        )
        code, output = _run_with_plan(root, sel, nodes, files)
        skipped = (
            f"Skipped: {_fmt(unselected + dropped)}"
            f" ({_fmt(unselected)} in unselected files,"
            f" {_fmt(dropped)} deselected inside selected files)"
        )
    if output.strip():
        print(output.rstrip())
    print(skipped)
    _print_warnings(sel)
    _print_confidence(sel)
    return code


def _run_with_plan(
    root: Path, sel: Selection, nodes: dict[str, FileNodes], files: list[str]
) -> tuple[int, str]:
    """Write the plan to a temp file and let the plugin apply it in pytest."""
    plan = plan_mod.build_plan(root, sel, nodes, summary="plan from the testsniper command")
    with tempfile.TemporaryDirectory(prefix="testsniper-") as tmp:
        path = Path(tmp) / "plan.json"
        plan_mod.write(path, plan)
        return run_pytest(root, files, plan_path=path)


if __name__ == "__main__":
    sys.exit(main())
