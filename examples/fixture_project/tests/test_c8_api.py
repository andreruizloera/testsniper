"""Tests for fixture_lib.c8.api."""

from fixture_lib.c8.api import api_value


def test_c8_api_00() -> None:
    assert api_value() + 0 == 111


def test_c8_api_01() -> None:
    assert api_value() + 1 == 112


def test_c8_api_02() -> None:
    assert api_value() + 2 == 113


def test_c8_api_03() -> None:
    assert api_value() + 3 == 114


def test_c8_api_04() -> None:
    assert api_value() + 4 == 115


def test_c8_api_05() -> None:
    assert api_value() + 5 == 116


def test_c8_api_06() -> None:
    assert api_value() + 6 == 117


def test_c8_api_07() -> None:
    assert api_value() + 7 == 118


def test_c8_api_08() -> None:
    assert api_value() + 8 == 119


def test_c8_api_09() -> None:
    assert api_value() + 9 == 120
