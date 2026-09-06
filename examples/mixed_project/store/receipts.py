"""Receipt rendering. Formats cents; it never computes them."""

from __future__ import annotations

DEFAULT_SYMBOL = "$"

# Module-level state, so a conftest has a real reason to reset it between
# tests. That reset is the autouse fixture in tests/conftest.py.
_currency = {"symbol": DEFAULT_SYMBOL}


def set_currency(symbol: str) -> None:
    """Change the symbol every later receipt is rendered with."""
    _currency["symbol"] = symbol


def reset_currency() -> None:
    """Put the symbol back, so one test cannot leak into the next."""
    _currency["symbol"] = DEFAULT_SYMBOL


def format_cents(cents: int) -> str:
    return f"{_currency['symbol']}{cents // 100}.{cents % 100:02d}"


def render_receipt(name: str, lines: list[tuple[str, int]]) -> str:
    """A plain-text receipt for already-computed line amounts."""
    out = [f"Receipt for {name}", "-" * 20]
    out.extend(f"{label}: {format_cents(amount)}" for label, amount in lines)
    return "\n".join(out)
