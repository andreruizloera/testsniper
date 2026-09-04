"""Chain c3, layer1 module."""

from fixture_lib.c3.base import base_value


def layer1_value() -> int:
    return base_value() + 1
