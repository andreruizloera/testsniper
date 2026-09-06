"""Fixtures shared by the tests in this directory.

Deliberately mixed, the same way test_checkout.py is. A change to pricing
reaches `taxed_total` and nothing else here, so an affected conftest does not
mean every test underneath it is affected. A change to receipts reaches the
autouse fixture, which does run for every test, and narrowing correctly gives
up on the whole directory for that one.
"""

import pytest

from store.orders import order_total
from store.receipts import reset_currency

BASKET = [("widget", 500, 2), ("gizmo", 250, 1)]


@pytest.fixture
def basket():
    """Just data: a pricing change does not reach it."""
    return list(BASKET)


@pytest.fixture
def taxed_total(basket):
    """Reaches pricing through orders, so the tests that ask for it do too."""
    return order_total(basket)


@pytest.fixture(autouse=True)
def _fresh_currency():
    """Runs for every test here, asked for or not."""
    reset_currency()
    yield
    reset_currency()
