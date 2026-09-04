"""Tests for fixture_lib.c8.base."""

from fixture_lib.c8.base import base_value


def test_c8_base_00() -> None:
    assert base_value() + 0 == 108


def test_c8_base_01() -> None:
    assert base_value() + 1 == 109


def test_c8_base_02() -> None:
    assert base_value() + 2 == 110


def test_c8_base_03() -> None:
    assert base_value() + 3 == 111


def test_c8_base_04() -> None:
    assert base_value() + 4 == 112


def test_c8_base_05() -> None:
    assert base_value() + 5 == 113


def test_c8_base_06() -> None:
    assert base_value() + 6 == 114


def test_c8_base_07() -> None:
    assert base_value() + 7 == 115


def test_c8_base_08() -> None:
    assert base_value() + 8 == 116


def test_c8_base_09() -> None:
    assert base_value() + 9 == 117
