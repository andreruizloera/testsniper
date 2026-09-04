"""Tests for fixture_lib.c4.base."""

from fixture_lib.c4.base import base_value


def test_c4_base_00() -> None:
    assert base_value() + 0 == 104


def test_c4_base_01() -> None:
    assert base_value() + 1 == 105


def test_c4_base_02() -> None:
    assert base_value() + 2 == 106


def test_c4_base_03() -> None:
    assert base_value() + 3 == 107


def test_c4_base_04() -> None:
    assert base_value() + 4 == 108


def test_c4_base_05() -> None:
    assert base_value() + 5 == 109


def test_c4_base_06() -> None:
    assert base_value() + 6 == 110


def test_c4_base_07() -> None:
    assert base_value() + 7 == 111


def test_c4_base_08() -> None:
    assert base_value() + 8 == 112


def test_c4_base_09() -> None:
    assert base_value() + 9 == 113
