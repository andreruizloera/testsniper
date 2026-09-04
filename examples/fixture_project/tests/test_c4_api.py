"""Tests for fixture_lib.c4.api."""

from fixture_lib.c4.api import api_value


def test_c4_api_00() -> None:
    assert api_value() + 0 == 107


def test_c4_api_01() -> None:
    assert api_value() + 1 == 108


def test_c4_api_02() -> None:
    assert api_value() + 2 == 109


def test_c4_api_03() -> None:
    assert api_value() + 3 == 110


def test_c4_api_04() -> None:
    assert api_value() + 4 == 111


def test_c4_api_05() -> None:
    assert api_value() + 5 == 112


def test_c4_api_06() -> None:
    assert api_value() + 6 == 113


def test_c4_api_07() -> None:
    assert api_value() + 7 == 114


def test_c4_api_08() -> None:
    assert api_value() + 8 == 115


def test_c4_api_09() -> None:
    assert api_value() + 9 == 116
