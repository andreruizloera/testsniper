"""Tests for test file indexing and counting."""

from __future__ import annotations

from pathlib import Path

from conftest import write_tree

from testsniper.config import Config
from testsniper.indexer import count_tests_in_file, index_tests, is_test_file, path_is_under
from testsniper.scanner import scan_repo


def test_naming_conventions() -> None:
    assert is_test_file("tests/test_foo.py")
    assert is_test_file("tests/foo_test.py")
    assert not is_test_file("tests/foo.py")
    assert not is_test_file("tests/test_data.json")
    assert not is_test_file("tests/conftest.py")


def test_path_is_under() -> None:
    assert path_is_under("tests/smoke/test_a.py", "tests/smoke")
    assert path_is_under("tests/test_a.py", "tests")
    assert not path_is_under("tests2/test_a.py", "tests")
    assert path_is_under("anything.py", ".")


def test_index_respects_testpaths(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "tests/test_in.py": "def test_a(): pass\n",
            "other/test_out.py": "def test_b(): pass\n",
        },
    )
    infos = scan_repo(tmp_path)
    picked = index_tests(tmp_path, infos, Config(testpaths=("tests",)))
    assert picked == ["tests/test_in.py"]


def test_index_defaults_to_tests_dir(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "tests/test_in.py": "def test_a(): pass\n",
            "stray/test_stray.py": "def test_b(): pass\n",
        },
    )
    infos = scan_repo(tmp_path)
    assert index_tests(tmp_path, infos, Config()) == ["tests/test_in.py"]


def test_index_falls_back_to_whole_repo(tmp_path: Path) -> None:
    write_tree(tmp_path, {"anywhere/test_x.py": "def test_a(): pass\n"})
    infos = scan_repo(tmp_path)
    assert index_tests(tmp_path, infos, Config()) == ["anywhere/test_x.py"]


def test_count_functions_and_class_methods(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "test_x.py": (
                "def test_one(): pass\n"
                "def test_two(): pass\n"
                "def helper(): pass\n"
                "async def test_async(): pass\n"
                "class TestThings:\n"
                "    def test_method(self): pass\n"
                "    def helper(self): pass\n"
                "class NotCollected:\n"
                "    def test_ignored(self): pass\n"
            )
        },
    )
    assert count_tests_in_file(tmp_path, "test_x.py") == 4


def test_count_unparseable_file_is_zero(tmp_path: Path) -> None:
    write_tree(tmp_path, {"test_bad.py": "def broken(:\n"})
    assert count_tests_in_file(tmp_path, "test_bad.py") == 0
