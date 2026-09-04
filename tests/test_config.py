"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.config import load_config


def test_defaults_when_no_pyproject(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.always_run == ()
    assert config.testpaths == ()


def test_always_run_and_testpaths_from_pyproject(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "pyproject.toml": (
                "[tool.testsniper]\n"
                'always_run = ["tests/smoke/", "tests/critical"]\n'
                "\n"
                "[tool.pytest.ini_options]\n"
                'testpaths = ["tests", "integration"]\n'
            )
        },
    )
    config = load_config(tmp_path)
    assert config.always_run == ("tests/smoke", "tests/critical")
    assert config.testpaths == ("tests", "integration")


def test_testpaths_as_string(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {"pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = "tests integration"\n'},
    )
    assert load_config(tmp_path).testpaths == ("tests", "integration")


def test_testpaths_from_pytest_ini(tmp_path: Path) -> None:
    write_tree(tmp_path, {"pytest.ini": "[pytest]\ntestpaths = tests more_tests\n"})
    assert load_config(tmp_path).testpaths == ("tests", "more_tests")


def test_broken_toml_is_ignored(tmp_path: Path) -> None:
    write_tree(tmp_path, {"pyproject.toml": "not [valid toml\n"})
    config = load_config(tmp_path)
    assert config.always_run == ()
