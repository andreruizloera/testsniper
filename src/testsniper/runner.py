"""Run pytest on the selected test files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_pytest(root: Path, files: list[str], plan_path: Path | None = None) -> tuple[int, str]:
    """Invoke pytest on the selected files and return (exit code, output).

    With a plan, the selected files are still passed (so pytest never
    collects more than it has to) and the plugin drops the individual tests
    inside them that the change cannot reach. The plugin is picked up through
    the ``pytest11`` entry point, so nothing has to be passed to load it.
    """
    cmd = [sys.executable, "-m", "pytest", "-q"]
    if plan_path is not None:
        cmd += ["--testsniper-plan", str(plan_path)]
    cmd += files
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 2, "error: could not launch the Python interpreter to run pytest"
    output = proc.stdout
    if proc.stderr.strip():
        output = f"{output}\n{proc.stderr}" if output else proc.stderr
    return proc.returncode, output
