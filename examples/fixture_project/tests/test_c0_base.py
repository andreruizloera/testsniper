"""Tests for fixture_lib.c0.base."""

from fixture_lib.c0.base import base_value


def test_c0_base_00() -> None:
    assert base_value() + 0 == 100


def test_c0_base_01() -> None:
    assert base_value() + 1 == 101


def test_c0_base_02() -> None:
    assert base_value() + 2 == 102


def test_c0_base_03() -> None:
    assert base_value() + 3 == 103


def test_c0_base_04() -> None:
    assert base_value() + 4 == 104


def test_c0_base_05() -> None:
    assert base_value() + 5 == 105


def test_c0_base_06() -> None:
    assert base_value() + 6 == 106


def test_c0_base_07() -> None:
    assert base_value() + 7 == 107


def test_c0_base_08() -> None:
    assert base_value() + 8 == 108


def test_c0_base_09() -> None:
    assert base_value() + 9 == 109
