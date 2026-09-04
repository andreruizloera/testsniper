"""Tests for fixture_lib.c0.api."""

from fixture_lib.c0.api import api_value


def test_c0_api_00() -> None:
    assert api_value() + 0 == 103


def test_c0_api_01() -> None:
    assert api_value() + 1 == 104


def test_c0_api_02() -> None:
    assert api_value() + 2 == 105


def test_c0_api_03() -> None:
    assert api_value() + 3 == 106


def test_c0_api_04() -> None:
    assert api_value() + 4 == 107


def test_c0_api_05() -> None:
    assert api_value() + 5 == 108


def test_c0_api_06() -> None:
    assert api_value() + 6 == 109


def test_c0_api_07() -> None:
    assert api_value() + 7 == 110


def test_c0_api_08() -> None:
    assert api_value() + 8 == 111


def test_c0_api_09() -> None:
    assert api_value() + 9 == 112
