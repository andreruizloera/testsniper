"""Run pytest on the selected test files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_pytest(root: Path, files: list[str]) -> tuple[int, str]:
    """Invoke pytest on the selected files and return (exit code, output)."""
    cmd = [sys.executable, "-m", "pytest", "-q", *files]
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 2, "error: could not launch the Python interpreter to run pytest"
    output = proc.stdout
    if proc.stderr.strip():
        output = f"{output}\n{proc.stderr}" if output else proc.stderr
    return proc.returncode, output
