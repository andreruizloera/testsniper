"""Tests for fixture_lib.c1.base."""

from fixture_lib.c1.base import base_value


def test_c1_base_00() -> None:
    assert base_value() + 0 == 101


def test_c1_base_01() -> None:
    assert base_value() + 1 == 102


def test_c1_base_02() -> None:
    assert base_value() + 2 == 103


def test_c1_base_03() -> None:
    assert base_value() + 3 == 104


def test_c1_base_04() -> None:
    assert base_value() + 4 == 105


def test_c1_base_05() -> None:
    assert base_value() + 5 == 106


def test_c1_base_06() -> None:
    assert base_value() + 6 == 107


def test_c1_base_07() -> None:
    assert base_value() + 7 == 108


def test_c1_base_08() -> None:
    assert base_value() + 8 == 109


def test_c1_base_09() -> None:
    assert base_value() + 9 == 110
