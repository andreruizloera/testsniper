"""Shipping cost, in whole cents, from parcel weight in grams."""

from __future__ import annotations

FLAT_CENTS = 599
PER_EXTRA_KILO_CENTS = 250


def shipping_cost(weight_g: int) -> int:
    """Flat rate up to a kilo, then a surcharge per started extra kilo."""
    if weight_g < 0:
        raise ValueError("weight cannot be negative")
    if weight_g <= 1000:
        return FLAT_CENTS
    extra_kilos = -(-(weight_g - 1000) // 1000)
    return FLAT_CENTS + extra_kilos * PER_EXTRA_KILO_CENTS
