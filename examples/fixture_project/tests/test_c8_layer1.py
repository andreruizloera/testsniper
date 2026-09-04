"""Tests for fixture_lib.c8.layer1."""

from fixture_lib.c8.layer1 import layer1_value


def test_c8_layer1_00() -> None:
    assert layer1_value() + 0 == 109


def test_c8_layer1_01() -> None:
    assert layer1_value() + 1 == 110


def test_c8_layer1_02() -> None:
    assert layer1_value() + 2 == 111


def test_c8_layer1_03() -> None:
    assert layer1_value() + 3 == 112


def test_c8_layer1_04() -> None:
    assert layer1_value() + 4 == 113


def test_c8_layer1_05() -> None:
    assert layer1_value() + 5 == 114


def test_c8_layer1_06() -> None:
    assert layer1_value() + 6 == 115


def test_c8_layer1_07() -> None:
    assert layer1_value() + 7 == 116


def test_c8_layer1_08() -> None:
    assert layer1_value() + 8 == 117


def test_c8_layer1_09() -> None:
    assert layer1_value() + 9 == 118
