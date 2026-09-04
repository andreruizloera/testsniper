"""Tests for fixture_lib.c5.api."""

from fixture_lib.c5.api import api_value


def test_c5_api_00() -> None:
    assert api_value() + 0 == 108


def test_c5_api_01() -> None:
    assert api_value() + 1 == 109


def test_c5_api_02() -> None:
    assert api_value() + 2 == 110


def test_c5_api_03() -> None:
    assert api_value() + 3 == 111


def test_c5_api_04() -> None:
    assert api_value() + 4 == 112


def test_c5_api_05() -> None:
    assert api_value() + 5 == 113


def test_c5_api_06() -> None:
    assert api_value() + 6 == 114


def test_c5_api_07() -> None:
    assert api_value() + 7 == 115


def test_c5_api_08() -> None:
    assert api_value() + 8 == 116


def test_c5_api_09() -> None:
    assert api_value() + 9 == 117
