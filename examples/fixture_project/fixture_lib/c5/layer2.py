"""Chain c5, layer2 module."""

from fixture_lib.c5.layer1 import layer1_value


def layer2_value() -> int:
    return layer1_value() + 1
