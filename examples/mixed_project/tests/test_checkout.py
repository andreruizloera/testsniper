"""Checkout tests.

Deliberately mixed: some tests use pricing, some use shipping, some only
format text. File-level selection has to run all of them when pricing
changes. Node-level selection does not.

The `basket` and `taxed_total` fixtures live in tests/conftest.py, so the
tests that use them reach pricing through a file this one never imports.
"""

import pytest

from store.orders import order_total, subtotal
from store.pricing import line_total, price_with_tax
from store.receipts import format_cents, render_receipt
from store.shipping import shipping_cost


def test_price_with_tax_rounds_half_up():
    assert price_with_tax(999) == 1074


def test_price_with_tax_of_zero_is_zero():
    assert price_with_tax(0) == 0


def test_price_with_tax_rejects_a_negative_price():
    with pytest.raises(ValueError):
        price_with_tax(-1)


@pytest.mark.parametrize(("unit", "quantity", "expected"), [(500, 2, 1000), (250, 0, 0)])
def test_line_total_multiplies(unit, quantity, expected):
    assert line_total(unit, quantity) == expected


def test_subtotal_sums_every_line(basket):
    assert subtotal(basket) == 1250


def test_order_total_applies_tax(basket):
    assert order_total(basket) == 1344


def test_receipt_shows_the_taxed_total(taxed_total):
    receipt = render_receipt("Ada", [("Total", taxed_total)])
    assert "Total: $13.44" in receipt


def test_shipping_is_flat_under_a_kilo():
    assert shipping_cost(250) == 599


def test_shipping_adds_a_surcharge_per_extra_kilo():
    assert shipping_cost(2500) == 1099


def test_receipt_lists_every_line():
    receipt = render_receipt("Ada", [("Widget", 500), ("Gizmo", 250)])
    assert "Widget: $5.00" in receipt
    assert "Gizmo: $2.50" in receipt


class TestReceiptFormatting:
    """A class, so the node key carries a class path."""

    def _render(self):
        return render_receipt("Ada", [("Shipping", 599)])

    def test_header_names_the_customer(self):
        assert self._render().startswith("Receipt for Ada")

    def test_amounts_are_dollars_and_cents(self):
        assert "Shipping: $5.99" in self._render()

    def test_format_cents_pads_the_cents(self):
        assert format_cents(5) == "$0.05"
