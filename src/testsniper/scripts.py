"""The console scripts a repository declares, read from its packaging metadata.

An installer turns one line of metadata, ``mytool = "mytool.cli:main"``, into
a program on PATH whose whole job is ``from mytool.cli import main`` and a
call to it. So a test that runs ``mytool --list`` depends on ``mytool.cli``
exactly as if it had imported it, and this metadata is the only place that
says so. ``entrypoints.py`` reads the program name out of the test; this
module reads what the name means.

Read, in every ``pyproject.toml`` and ``setup.cfg`` in the repository:

- ``[project.scripts]`` and ``[project.gui-scripts]``, the standard tables;
- ``[tool.poetry.scripts]``, as a string or as a table whose ``reference``
  is a module and whose ``type`` is ``console``;
- ``console_scripts`` and ``gui_scripts`` under ``[options.entry_points]``
  in ``setup.cfg``.

Every file is read, not only the one at the root, because a nested project's
script still runs code the scan can see. A name declared twice maps to both
modules: following both can over-select and cannot under-select.

Not read: ``setup.py``, which is code rather than metadata, and a poetry
script whose ``type`` is ``file``, which names a file rather than a module.
A declared name that is ALSO an unrelated executable on PATH is followed
anyway. The project declared it, so a test in this repository that runs
that name most likely means this script, and when it does not, the cost is
one test run that did not need to happen.
"""

from __future__ import annotations

import configparser
import tomllib
from collections.abc import Collection, Mapping
from pathlib import Path

__all__ = [
    "Scripts",
    "entry_point_module",
    "load_scripts",
    "pyproject_scripts",
    "setup_cfg_scripts",
]

# Console-script name -> every module a script of that name imports.
Scripts = Mapping[str, frozenset[str]]

METADATA_FILES: tuple[str, ...] = ("pyproject.toml", "setup.cfg")


def entry_point_module(reference: str) -> str | None:
    """The module an entry-point object reference imports.

    ``pkg.cli:main`` imports ``pkg.cli``, and so do ``pkg.cli:Group.main``
    and a bare ``pkg.cli``. Extras in brackets (``pkg.cli:main [color]``)
    are dropped. Anything that is not a dotted identifier is refused.
    """
    text = reference.split("[", 1)[0]
    module = text.split(":", 1)[0].strip()
    if module and all(part.isidentifier() for part in module.split(".")):
        return module
    return None


def _add(found: dict[str, set[str]], name: object, reference: object) -> None:
    if not isinstance(name, str) or not isinstance(reference, str):
        return
    module = entry_point_module(reference)
    if name.strip() and module is not None:
        found.setdefault(name.strip(), set()).add(module)


def pyproject_scripts(data: Mapping[str, object]) -> dict[str, set[str]]:
    """Console scripts declared in one parsed ``pyproject.toml``."""
    found: dict[str, set[str]] = {}
    project = data.get("project")
    if isinstance(project, dict):
        for table in ("scripts", "gui-scripts"):
            entries = project.get(table)
            if isinstance(entries, dict):
                for name, reference in entries.items():
                    _add(found, name, reference)

    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    entries = poetry.get("scripts") if isinstance(poetry, dict) else None
    if isinstance(entries, dict):
        for name, value in entries.items():
            if isinstance(value, dict):
                if value.get("type") != "console":
                    continue
                value = value.get("reference")
            _add(found, name, value)
    return found


def setup_cfg_scripts(text: str) -> dict[str, set[str]]:
    """Console scripts declared in one ``setup.cfg``."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error:
        return {}
    found: dict[str, set[str]] = {}
    for group in ("console_scripts", "gui_scripts"):
        raw = parser.get("options.entry_points", group, fallback="")
        for line in raw.splitlines():
            name, sep, reference = line.partition("=")
            if sep:
                _add(found, name, reference)
    return found


def load_scripts(root: Path, skip_dirs: Collection[str] = ()) -> dict[str, frozenset[str]]:
    """Every console script declared anywhere under ``root``.

    ``skip_dirs`` are directory names never read from, which is what keeps a
    virtualenv's installed packages from declaring scripts for this
    repository. A file that cannot be read or parsed contributes nothing.
    """
    found: dict[str, set[str]] = {}
    for filename in METADATA_FILES:
        for path in sorted(root.rglob(filename)):
            if any(part in skip_dirs for part in path.relative_to(root).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
                if filename == "pyproject.toml":
                    declared = pyproject_scripts(tomllib.loads(text))
                else:
                    declared = setup_cfg_scripts(text)
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
                continue
            for name, modules in declared.items():
                found.setdefault(name, set()).update(modules)
    return {name: frozenset(modules) for name, modules in found.items()}
