"""Prices, in whole cents. Tax rounds half up."""

from __future__ import annotations

TAX_RATE = 0.075


def price_with_tax(cents: int) -> int:
    """Add sales tax to a price, rounding to the nearest cent, half up."""
    if cents < 0:
        raise ValueError("price cannot be negative")
    return int(cents + cents * TAX_RATE + 0.5)


def line_total(unit_cents: int, quantity: int) -> int:
    """Total for one order line, before tax."""
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    return unit_cents * quantity
