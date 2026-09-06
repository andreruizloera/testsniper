"""Shipping only. A pricing change never reaches this file at all."""

import pytest

from store.shipping import FLAT_CENTS, shipping_cost


@pytest.mark.parametrize("weight", [0, 1, 500, 1000])
def test_flat_rate_up_to_a_kilo(weight):
    assert shipping_cost(weight) == FLAT_CENTS


def test_one_gram_over_a_kilo_starts_the_surcharge():
    assert shipping_cost(1001) == FLAT_CENTS + 250


def test_negative_weight_is_rejected():
    with pytest.raises(ValueError):
        shipping_cost(-1)
