"""Tests for fixture_lib.c3.api."""

from fixture_lib.c3.api import api_value


def test_c3_api_00() -> None:
    assert api_value() + 0 == 106


def test_c3_api_01() -> None:
    assert api_value() + 1 == 107


def test_c3_api_02() -> None:
    assert api_value() + 2 == 108


def test_c3_api_03() -> None:
    assert api_value() + 3 == 109


def test_c3_api_04() -> None:
    assert api_value() + 4 == 110


def test_c3_api_05() -> None:
    assert api_value() + 5 == 111


def test_c3_api_06() -> None:
    assert api_value() + 6 == 112


def test_c3_api_07() -> None:
    assert api_value() + 7 == 113


def test_c3_api_08() -> None:
    assert api_value() + 8 == 114


def test_c3_api_09() -> None:
    assert api_value() + 9 == 115
