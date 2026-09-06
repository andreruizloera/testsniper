"""Reporting tests, which import nothing a pricing change touches.

This file imports one formatting helper out of store.receipts, and a pricing
change never reaches receipts. The only path from pricing to the test below is
the taxed_total fixture in tests/conftest.py, which this file names and never
imports, so the import graph alone cannot see the connection at all.
"""

from store.receipts import format_cents


def test_the_taxed_total_is_rendered_as_dollars(taxed_total):
    assert format_cents(taxed_total) == "$13.44"


def test_a_basket_has_one_line_per_item(basket):
    assert len(basket) == 2


def test_zero_renders_as_zero():
    assert format_cents(0) == "$0.00"
