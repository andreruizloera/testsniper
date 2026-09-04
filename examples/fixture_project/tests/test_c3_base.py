"""Tests for fixture_lib.c3.base."""

from fixture_lib.c3.base import base_value


def test_c3_base_00() -> None:
    assert base_value() + 0 == 103


def test_c3_base_01() -> None:
    assert base_value() + 1 == 104


def test_c3_base_02() -> None:
    assert base_value() + 2 == 105


def test_c3_base_03() -> None:
    assert base_value() + 3 == 106


def test_c3_base_04() -> None:
    assert base_value() + 4 == 107


def test_c3_base_05() -> None:
    assert base_value() + 5 == 108


def test_c3_base_06() -> None:
    assert base_value() + 6 == 109


def test_c3_base_07() -> None:
    assert base_value() + 7 == 110


def test_c3_base_08() -> None:
    assert base_value() + 8 == 111


def test_c3_base_09() -> None:
    assert base_value() + 9 == 112
