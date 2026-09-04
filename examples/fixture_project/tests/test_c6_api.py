"""Tests for fixture_lib.c6.api."""

from fixture_lib.c6.api import api_value


def test_c6_api_00() -> None:
    assert api_value() + 0 == 109


def test_c6_api_01() -> None:
    assert api_value() + 1 == 110


def test_c6_api_02() -> None:
    assert api_value() + 2 == 111


def test_c6_api_03() -> None:
    assert api_value() + 3 == 112


def test_c6_api_04() -> None:
    assert api_value() + 4 == 113


def test_c6_api_05() -> None:
    assert api_value() + 5 == 114


def test_c6_api_06() -> None:
    assert api_value() + 6 == 115


def test_c6_api_07() -> None:
    assert api_value() + 7 == 116


def test_c6_api_08() -> None:
    assert api_value() + 8 == 117


def test_c6_api_09() -> None:
    assert api_value() + 9 == 118
