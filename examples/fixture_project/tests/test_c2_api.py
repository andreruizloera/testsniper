"""Tests for fixture_lib.c2.api."""

from fixture_lib.c2.api import api_value


def test_c2_api_00() -> None:
    assert api_value() + 0 == 105


def test_c2_api_01() -> None:
    assert api_value() + 1 == 106


def test_c2_api_02() -> None:
    assert api_value() + 2 == 107


def test_c2_api_03() -> None:
    assert api_value() + 3 == 108


def test_c2_api_04() -> None:
    assert api_value() + 4 == 109


def test_c2_api_05() -> None:
    assert api_value() + 5 == 110


def test_c2_api_06() -> None:
    assert api_value() + 6 == 111


def test_c2_api_07() -> None:
    assert api_value() + 7 == 112


def test_c2_api_08() -> None:
    assert api_value() + 8 == 113


def test_c2_api_09() -> None:
    assert api_value() + 9 == 114
