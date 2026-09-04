"""Tests for fixture_lib.c1.api."""

from fixture_lib.c1.api import api_value


def test_c1_api_00() -> None:
    assert api_value() + 0 == 104


def test_c1_api_01() -> None:
    assert api_value() + 1 == 105


def test_c1_api_02() -> None:
    assert api_value() + 2 == 106


def test_c1_api_03() -> None:
    assert api_value() + 3 == 107


def test_c1_api_04() -> None:
    assert api_value() + 4 == 108


def test_c1_api_05() -> None:
    assert api_value() + 5 == 109


def test_c1_api_06() -> None:
    assert api_value() + 6 == 110


def test_c1_api_07() -> None:
    assert api_value() + 7 == 111


def test_c1_api_08() -> None:
    assert api_value() + 8 == 112


def test_c1_api_09() -> None:
    assert api_value() + 9 == 113
