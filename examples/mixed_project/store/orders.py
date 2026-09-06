"""Order totals. Imports pricing, so a pricing change reaches it at distance 2."""

from __future__ import annotations

from store.pricing import line_total, price_with_tax


def subtotal(items: list[tuple[str, int, int]]) -> int:
    """Sum every line in an order, before tax."""
    return sum(line_total(unit, qty) for _name, unit, qty in items)


def order_total(items: list[tuple[str, int, int]]) -> int:
    """Order subtotal with tax applied."""
    return price_with_tax(subtotal(items))
