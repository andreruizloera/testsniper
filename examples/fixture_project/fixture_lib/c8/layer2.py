"""Chain c8, layer2 module."""

from fixture_lib.c8.layer1 import layer1_value


def layer2_value() -> int:
    return layer1_value() + 1
