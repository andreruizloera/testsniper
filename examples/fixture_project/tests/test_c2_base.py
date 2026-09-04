"""Tests for fixture_lib.c2.base."""

from fixture_lib.c2.base import base_value


def test_c2_base_00() -> None:
    assert base_value() + 0 == 102


def test_c2_base_01() -> None:
    assert base_value() + 1 == 103


def test_c2_base_02() -> None:
    assert base_value() + 2 == 104


def test_c2_base_03() -> None:
    assert base_value() + 3 == 105


def test_c2_base_04() -> None:
    assert base_value() + 4 == 106


def test_c2_base_05() -> None:
    assert base_value() + 5 == 107


def test_c2_base_06() -> None:
    assert base_value() + 6 == 108


def test_c2_base_07() -> None:
    assert base_value() + 7 == 109


def test_c2_base_08() -> None:
    assert base_value() + 8 == 110


def test_c2_base_09() -> None:
    assert base_value() + 9 == 111
