"""Smoke tests, wired into [tool.testsniper] always_run."""

from fixture_lib.c0.api import api_value


def test_smoke_api_chain_zero() -> None:
    assert api_value() == 103


def test_smoke_arithmetic() -> None:
    assert 1 + 1 == 2
