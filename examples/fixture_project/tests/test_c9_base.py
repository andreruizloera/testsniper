"""Tests for fixture_lib.c9.base."""

from fixture_lib.c9.base import base_value


def test_c9_base_00() -> None:
    assert base_value() + 0 == 109


def test_c9_base_01() -> None:
    assert base_value() + 1 == 110


def test_c9_base_02() -> None:
    assert base_value() + 2 == 111


def test_c9_base_03() -> None:
    assert base_value() + 3 == 112


def test_c9_base_04() -> None:
    assert base_value() + 4 == 113


def test_c9_base_05() -> None:
    assert base_value() + 5 == 114


def test_c9_base_06() -> None:
    assert base_value() + 6 == 115


def test_c9_base_07() -> None:
    assert base_value() + 7 == 116


def test_c9_base_08() -> None:
    assert base_value() + 8 == 117


def test_c9_base_09() -> None:
    assert base_value() + 9 == 118
