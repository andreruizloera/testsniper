"""Configuration loading from pyproject.toml and pytest.ini."""

from __future__ import annotations

import configparser
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Resolved testsniper configuration for a repository."""

    always_run: tuple[str, ...] = ()
    testpaths: tuple[str, ...] = ()


def _normalize_path(value: str) -> str:
    return value.strip().strip("/").rstrip("/")


def load_config(root: Path) -> Config:
    """Read [tool.testsniper] and pytest testpaths for the target repo.

    Sources, in order: pyproject.toml ([tool.testsniper] and
    [tool.pytest.ini_options]), then pytest.ini for testpaths if
    pyproject did not set them.
    """
    always_run: tuple[str, ...] = ()
    testpaths: tuple[str, ...] = ()

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        tool = data.get("tool", {})
        sniper = tool.get("testsniper", {})
        raw_always = sniper.get("always_run", [])
        if isinstance(raw_always, list):
            always_run = tuple(_normalize_path(p) for p in raw_always if isinstance(p, str) and p)
        raw_paths = tool.get("pytest", {}).get("ini_options", {}).get("testpaths", [])
        if isinstance(raw_paths, str):
            raw_paths = raw_paths.split()
        if isinstance(raw_paths, list):
            testpaths = tuple(_normalize_path(p) for p in raw_paths if isinstance(p, str) and p)

    if not testpaths:
        pytest_ini = root / "pytest.ini"
        if pytest_ini.is_file():
            parser = configparser.ConfigParser()
            try:
                parser.read(pytest_ini, encoding="utf-8")
                raw = parser.get("pytest", "testpaths", fallback="")
                testpaths = tuple(_normalize_path(p) for p in raw.split() if p)
            except configparser.Error:
                pass

    return Config(always_run=always_run, testpaths=testpaths)
