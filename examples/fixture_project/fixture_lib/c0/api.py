"""Chain c0, api module."""

from fixture_lib.c0.layer2 import layer2_value


def api_value() -> int:
    return layer2_value() + 1
