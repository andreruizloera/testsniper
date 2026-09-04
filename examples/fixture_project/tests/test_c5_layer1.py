"""Tests for fixture_lib.c5.layer1."""

from fixture_lib.c5.layer1 import layer1_value


def test_c5_layer1_00() -> None:
    assert layer1_value() + 0 == 106


def test_c5_layer1_01() -> None:
    assert layer1_value() + 1 == 107


def test_c5_layer1_02() -> None:
    assert layer1_value() + 2 == 108


def test_c5_layer1_03() -> None:
    assert layer1_value() + 3 == 109


def test_c5_layer1_04() -> None:
    assert layer1_value() + 4 == 110


def test_c5_layer1_05() -> None:
    assert layer1_value() + 5 == 111


def test_c5_layer1_06() -> None:
    assert layer1_value() + 6 == 112


def test_c5_layer1_07() -> None:
    assert layer1_value() + 7 == 113


def test_c5_layer1_08() -> None:
    assert layer1_value() + 8 == 114


def test_c5_layer1_09() -> None:
    assert layer1_value() + 9 == 115
