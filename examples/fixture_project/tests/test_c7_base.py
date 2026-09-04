"""Tests for fixture_lib.c7.base."""

from fixture_lib.c7.base import base_value


def test_c7_base_00() -> None:
    assert base_value() + 0 == 107


def test_c7_base_01() -> None:
    assert base_value() + 1 == 108


def test_c7_base_02() -> None:
    assert base_value() + 2 == 109


def test_c7_base_03() -> None:
    assert base_value() + 3 == 110


def test_c7_base_04() -> None:
    assert base_value() + 4 == 111


def test_c7_base_05() -> None:
    assert base_value() + 5 == 112


def test_c7_base_06() -> None:
    assert base_value() + 6 == 113


def test_c7_base_07() -> None:
    assert base_value() + 7 == 114


def test_c7_base_08() -> None:
    assert base_value() + 8 == 115


def test_c7_base_09() -> None:
    assert base_value() + 9 == 116
