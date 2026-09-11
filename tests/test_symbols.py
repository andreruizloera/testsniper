"""Reading a changed module's own diff for the symbols the change reaches.

The cases that matter here are the ones where narrowing must NOT happen.
Dropping a test that could have caught the change is the only failure worth
preventing; keeping one that cannot is merely slow.
"""

from __future__ import annotations

from testsniper.symbols import changed_symbols, propagate_symbols

BASE = '''"""Two unrelated helpers."""

RATE = 0.1


def line_total(unit, quantity):
    """Total for one line."""
    return unit * quantity


def price_with_tax(amount):
    """Amount plus tax."""
    return amount * (1 + RATE)
'''


def _symbols(new: str, old: str = BASE, relpath: str = "pricing/core.py"):
    return changed_symbols(relpath, old, new, ["pricing"])


def test_editing_one_function_names_only_that_function() -> None:
    new = BASE.replace("return amount * (1 + RATE)", "return round(amount * (1 + RATE), 2)")
    result = _symbols(new)
    assert result.usable
    assert result.names == {"price_with_tax"}


def test_a_caller_of_a_changed_function_comes_back_too() -> None:
    """line_total does not change, but what it computes does."""
    old = BASE.replace("return unit * quantity", "return unit * quantity")
    chained = old.replace(
        "    return unit * quantity", "    return price_with_tax(unit * quantity)"
    )
    new = chained.replace("return amount * (1 + RATE)", "return round(amount * (1 + RATE), 2)")
    result = _symbols(new, old=chained)
    assert result.usable
    assert result.names == {"price_with_tax", "line_total"}


def test_a_comment_only_edit_reaches_nothing() -> None:
    new = BASE.replace("RATE = 0.1", "RATE = 0.1  # standard rate")
    result = _symbols(new)
    assert result.usable
    assert result.names == frozenset()


def test_a_docstring_edit_is_a_change() -> None:
    """--doctest-modules can collect a docstring, so it is not cosmetic."""
    new = BASE.replace('"""Amount plus tax."""', '"""Amount plus tax, to cents."""')
    result = _symbols(new)
    assert result.usable
    assert result.names == {"price_with_tax"}


def test_reflowing_a_body_reaches_nothing() -> None:
    new = BASE.replace(
        "    return amount * (1 + RATE)",
        "    return amount * (\n        1 + RATE\n    )",
    )
    result = _symbols(new)
    assert result.usable
    assert result.names == frozenset()


def test_module_level_code_that_changed_blocks_the_whole_module() -> None:
    new = BASE.replace("RATE = 0.1", "RATE = 0.2")
    result = _symbols(new)
    assert not result.usable
    assert "module-level code in pricing/core.py changed" in (result.block or "")


def test_module_level_code_reading_a_changed_symbol_blocks() -> None:
    """The statement itself did not move, but the value it computes did."""
    old = BASE + "\n\nDEFAULT = price_with_tax(100)\n"
    new = old.replace("return amount * (1 + RATE)", "return round(amount * (1 + RATE), 2)")
    result = _symbols(new, old=old)
    assert not result.usable
    assert "reads something the diff changed" in (result.block or "")


def test_a_deleted_function_is_named() -> None:
    new = BASE.replace(
        'def price_with_tax(amount):\n    """Amount plus tax."""\n    return amount * (1 + RATE)\n',
        "",
    )
    result = _symbols(new)
    assert result.usable
    assert "price_with_tax" in result.names


def test_an_added_function_names_only_itself() -> None:
    new = BASE + "\n\ndef bulk_discount(cents):\n    return cents * 9 // 10\n"
    result = _symbols(new)
    assert result.usable
    assert result.names == {"bulk_discount"}


def test_a_class_is_one_symbol_and_a_method_edit_moves_it() -> None:
    old = BASE + "\n\nclass Cart:\n    def total(self):\n        return 0\n"
    new = old.replace("        return 0", "        return 1")
    result = _symbols(new, old=old)
    assert result.usable
    assert result.names == {"Cart"}


def test_a_class_reaches_a_changed_function_through_its_base() -> None:
    old = BASE + "\n\nclass Cart:\n    pass\n\n\nclass Basket(Cart):\n    pass\n"
    new = old.replace("class Cart:\n    pass", "class Cart:\n    total = 0")
    result = _symbols(new, old=old)
    assert result.usable
    assert result.names == {"Cart", "Basket"}


def test_a_moved_import_names_what_it_binds() -> None:
    old = "from pricing.tax import rate\n\n\ndef f():\n    return rate()\n"
    new = "from pricing.tax import rate, other\n\n\ndef f():\n    return rate()\n"
    result = _symbols(new, old=old)
    assert result.usable
    assert {"rate", "other", "f"} <= result.names


def test_a_moved_star_import_blocks() -> None:
    old = "from pricing.tax import *\n\n\ndef f():\n    return 1\n"
    new = "from pricing.tax import *  # noqa\n\n\ndef g():\n    return 1\n"
    result = _symbols(new, old=old)
    # The star itself is unmoved here; move it and the answer is a block.
    moved = _symbols("from pricing.other import *\n\n\ndef f():\n    return 1\n", old=old)
    assert not moved.usable
    assert "star import" in (moved.block or "")
    assert result.usable


def test_a_dynamic_import_blocks() -> None:
    old = "import importlib\n\n\ndef f():\n    return importlib.import_module('x')\n"
    new = old.replace("return importlib", "return  importlib")
    result = _symbols(new, old=old)
    assert not result.usable
    assert "imports dynamically" in (result.block or "")


def test_a_module_level_getattr_blocks() -> None:
    old = BASE + "\n\ndef __getattr__(name):\n    return 1\n"
    new = old.replace("return unit * quantity", "return quantity * unit")
    result = _symbols(new, old=old)
    assert not result.usable
    assert "__getattr__" in (result.block or "")


def test_a_new_module_blocks() -> None:
    result = changed_symbols("pricing/core.py", None, BASE, ["pricing"])
    assert not result.usable
    assert "is new" in (result.block or "")


def test_an_unparseable_revision_blocks() -> None:
    result = _symbols(BASE, old="def broken(:\n")
    assert not result.usable
    assert "could not be parsed" in (result.block or "")


def test_module_level_code_that_reads_names_dynamically_blocks() -> None:
    old = BASE + "\n\nNAMES = sorted(globals())\n"
    new = old.replace("return unit * quantity", "return quantity * unit")
    result = _symbols(new, old=old)
    assert not result.usable
    assert "reads names dynamically" in (result.block or "")


MID = '''"""A module downstream of the change, with no diff of its own."""

from pricing.core import line_total, price_with_tax


def taxed_line(unit, quantity):
    return price_with_tax(line_total(unit, quantity))


def plain_line(unit, quantity):
    return line_total(unit, quantity)
'''


def _propagated(
    source: str = MID,
    affected: set[str] | None = None,
    symbols: dict[str, frozenset[str]] | None = None,
    **kwargs,
):
    return propagate_symbols(
        "orders/mid.py",
        source,
        ["orders"],
        affected if affected is not None else {"pricing.core"},
        symbols if symbols is not None else {"pricing.core": frozenset({"price_with_tax"})},
        **kwargs,
    )


def test_only_the_definitions_that_read_the_changed_symbol_propagate() -> None:
    """The caveat this feature exists for: narrowing used to die at hop one.

    plain_line calls line_total, which the change never reached, so nothing
    downstream of plain_line can see the change either.
    """
    result = _propagated()
    assert result.usable
    assert result.names == {"price_with_tax", "taxed_line"}


def test_a_downstream_module_that_reads_nothing_affected_is_empty_not_blocked() -> None:
    """Being in the closure means importing an affected MODULE, not a SYMBOL.

    An empty answer here is the honest one, and refusing instead would put the
    wholesale re-export straight back.
    """
    result = _propagated(symbols={"pricing.core": frozenset({"unrelated"})})
    assert result.usable
    assert result.names == frozenset()


def test_an_unreadable_upstream_module_taints_every_importer_of_its_names() -> None:
    """A module absent from the map has all of its symbols affected."""
    result = _propagated(symbols={})
    assert result.usable
    assert result.names == {"price_with_tax", "line_total", "taxed_line", "plain_line"}


def test_a_module_that_is_changed_and_downstream_unions_both_answers() -> None:
    """The under-selection this fix is really about.

    plain_line moved in this module's own diff; taxed_line reads a symbol that
    moved upstream. Either answer alone drops tests the change reaches.
    """
    result = _propagated(seeds=frozenset({"plain_line"}))
    assert result.usable
    assert result.names == {"price_with_tax", "taxed_line", "plain_line"}


def test_module_level_code_reading_an_affected_import_blocks() -> None:
    source = MID + "\nREADY = price_with_tax(100)\n"
    result = _propagated(source)
    assert not result.usable
    assert "runs on import" in str(result.block)


def test_a_function_local_import_taints_only_its_own_function() -> None:
    source = '''"""Nothing at module level reaches the change."""


def uses_it(amount):
    from pricing.core import price_with_tax

    return price_with_tax(amount)


def does_not(amount):
    return amount
'''
    result = _propagated(source)
    assert result.usable
    assert result.names == {"uses_it"}


def test_a_star_import_from_an_affected_module_blocks() -> None:
    result = _propagated("from pricing.core import *\n\n\ndef f():\n    return 1\n")
    assert not result.usable
    assert "star import" in str(result.block)


def test_an_affected_parent_package_blocks_a_submodule_import() -> None:
    """Importing pricing.core runs pricing/__init__.py first.

    No name bound by the import stands for that side effect, so there is
    nothing for usage tracking to follow and narrowing must refuse.
    """
    result = _propagated(affected={"pricing.core", "pricing"}, symbols={})
    assert not result.usable
    assert "runs on import" in str(result.block)


def test_an_affected_parent_with_readable_symbols_does_not_block() -> None:
    """A package whose own symbols were read has module-level code known inert.

    Without this exclusion the common re-exporting __init__ would make every
    submodule import in the repository unnarrowable.
    """
    result = _propagated(
        affected={"pricing.core", "pricing"},
        symbols={
            "pricing.core": frozenset({"price_with_tax"}),
            "pricing": frozenset({"price_with_tax"}),
        },
    )
    assert result.usable
    assert result.names == {"price_with_tax", "taxed_line"}
