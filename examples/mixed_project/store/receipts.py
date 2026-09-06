"""Receipt rendering. Formats cents; it never computes them."""

from __future__ import annotations


def format_cents(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def render_receipt(name: str, lines: list[tuple[str, int]]) -> str:
    """A plain-text receipt for already-computed line amounts."""
    out = [f"Receipt for {name}", "-" * 20]
    out.extend(f"{label}: {format_cents(amount)}" for label, amount in lines)
    return "\n".join(out)
