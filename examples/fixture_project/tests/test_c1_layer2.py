"""Tests for fixture_lib.c1.layer2."""

from fixture_lib.c1.layer2 import layer2_value


def test_c1_layer2_00() -> None:
    assert layer2_value() + 0 == 103


def test_c1_layer2_01() -> None:
    assert layer2_value() + 1 == 104


def test_c1_layer2_02() -> None:
    assert layer2_value() + 2 == 105


def test_c1_layer2_03() -> None:
    assert layer2_value() + 3 == 106


def test_c1_layer2_04() -> None:
    assert layer2_value() + 4 == 107


def test_c1_layer2_05() -> None:
    assert layer2_value() + 5 == 108


def test_c1_layer2_06() -> None:
    assert layer2_value() + 6 == 109


def test_c1_layer2_07() -> None:
    assert layer2_value() + 7 == 110


def test_c1_layer2_08() -> None:
    assert layer2_value() + 8 == 111


def test_c1_layer2_09() -> None:
    assert layer2_value() + 9 == 112
