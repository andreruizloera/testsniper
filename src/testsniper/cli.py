"""Command-line interface for testsniper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from testsniper import __version__
from testsniper.config import load_config
from testsniper.gitio import GitError, changed_files, repo_root
from testsniper.runner import run_pytest
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
    parser.add_argument("--version", action="version", version=f"testsniper {__version__}")
    return parser


def _print_confidence(sel: Selection) -> None:
    print(f"Selection confidence: {sel.confidence}")
    for reason in sel.confidence_reasons:
        print(f"  - {reason}")


def _print_warnings(sel: Selection) -> None:
    for rel in sel.unreached:
        print(f"Warning: no test reaches changed module {rel}")


def _print_list(sel: Selection) -> None:
    print(f"Selected (would run {_fmt(sel.selected_tests)} of {_fmt(sel.total_tests)} tests):")
    for test in sel.tests:
        where = "always" if test.distance is None else f"distance {test.distance}"
        print(f"  {test.relpath}  [{where}] {test.reason}")
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
    sel = select(root, changed, mode, config)

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
        _print_list(sel)
        return 0

    if not sel.tests:
        print("No tests selected.")
        _print_warnings(sel)
        _print_confidence(sel)
        return 0

    print(f"Running {_fmt(sel.selected_tests)} of {_fmt(sel.total_tests)} tests...")
    code, output = run_pytest(root, [t.relpath for t in sel.tests])
    if output.strip():
        print(output.rstrip())
    print(f"Skipped: {_fmt(sel.total_tests - sel.selected_tests)} (not selected)")
    _print_warnings(sel)
    _print_confidence(sel)
    return code


if __name__ == "__main__":
    sys.exit(main())
