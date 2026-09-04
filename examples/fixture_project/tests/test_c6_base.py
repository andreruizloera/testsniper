"""Tests for fixture_lib.c6.base."""

from fixture_lib.c6.base import base_value


def test_c6_base_00() -> None:
    assert base_value() + 0 == 106


def test_c6_base_01() -> None:
    assert base_value() + 1 == 107


def test_c6_base_02() -> None:
    assert base_value() + 2 == 108


def test_c6_base_03() -> None:
    assert base_value() + 3 == 109


def test_c6_base_04() -> None:
    assert base_value() + 4 == 110


def test_c6_base_05() -> None:
    assert base_value() + 5 == 111


def test_c6_base_06() -> None:
    assert base_value() + 6 == 112


def test_c6_base_07() -> None:
    assert base_value() + 7 == 113


def test_c6_base_08() -> None:
    assert base_value() + 8 == 114


def test_c6_base_09() -> None:
    assert base_value() + 9 == 115
