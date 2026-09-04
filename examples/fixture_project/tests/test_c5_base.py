"""Tests for fixture_lib.c5.base."""

from fixture_lib.c5.base import base_value


def test_c5_base_00() -> None:
    assert base_value() + 0 == 105


def test_c5_base_01() -> None:
    assert base_value() + 1 == 106


def test_c5_base_02() -> None:
    assert base_value() + 2 == 107


def test_c5_base_03() -> None:
    assert base_value() + 3 == 108


def test_c5_base_04() -> None:
    assert base_value() + 4 == 109


def test_c5_base_05() -> None:
    assert base_value() + 5 == 110


def test_c5_base_06() -> None:
    assert base_value() + 6 == 111


def test_c5_base_07() -> None:
    assert base_value() + 7 == 112


def test_c5_base_08() -> None:
    assert base_value() + 8 == 113


def test_c5_base_09() -> None:
    assert base_value() + 9 == 114
