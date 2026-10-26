# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Install a macro's filter cards and apply them once.

Column names in *clauses* are already resolved (no ``${step.key}`` left).
``on_done`` runs when the filter pass finishes, including a pass that goes
through the chunked or SQLite path. It is ``on_done(error)`` with ``error``
``None`` on success.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..platform_support.config import load_config
from ..workflows.macro_recipe import FILTER_NUMERIC, FILTER_SUBSTRUCTURE, FILTER_TEXT


def ensure_numeric_bounds(app: Any, names: Sequence[str]) -> None:
    """Fill ``global_bounds`` for columns a later macro step is about to read.

    Large descriptor writes only schedule a full bounds scan. The next step
    needs the new columns immediately, so scan those headers here.
    """
    bounds = getattr(app, "global_bounds", None)
    headers = list(getattr(app, "headers", None) or [])
    if not isinstance(bounds, dict):
        return
    missing = [
        str(name) for name in names if name and str(name) in headers and str(name) not in bounds
    ]
    if not missing:
        return
    sync = getattr(app, "_sync_global_bounds_for_headers", None)
    if callable(sync):
        sync(missing, refresh_filters=False)


def start_macro_filters(
    app: Any,
    clauses: Sequence[dict[str, Any]],
    *,
    replace: bool,
    on_done: Callable[[str | None], None],
) -> None:
    """Replace or extend the filter panel, then apply. *on_done* may run before return."""
    cards: list[Any] = []
    for index, clause in enumerate(clauses, start=1):
        card = _build_card(app, clause, index)
        if isinstance(card, str):
            on_done(card)
            return
        cards.append(card)
    if not cards:
        on_done("Add at least one filter.")
        return
    if replace:
        app.replace_filter_cards(cards)
    else:
        for index, card in enumerate(cards, start=1):
            app._append_filter_widget(card, title=f"Macro {index}")
    panel = getattr(app, "f_panel", None)
    if panel is not None:
        panel.setVisible(True)
    app._macro_filter_done = lambda: on_done(None)
    try:
        app._apply_filters_impl(load_config())
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        app._macro_filter_done = None
        on_done(str(exc) or "Could not apply filters.")


def _build_card(app: Any, clause: dict[str, Any], index: int) -> Any:
    kind = str(clause.get("kind") or "")
    title = f"Macro {index}"
    inverted = bool(clause.get("inverted", False))
    if kind == FILTER_NUMERIC:
        return _numeric_card(app, clause, title, inverted)
    if kind == FILTER_TEXT:
        return _text_card(app, clause, title, inverted)
    if kind == FILTER_SUBSTRUCTURE:
        return _substructure_card(app, clause, title, inverted)
    return f"Filter {index} has an unknown kind."


def _numeric_card(app: Any, clause: dict[str, Any], title: str, inverted: bool) -> Any:
    from .filters.numeric_card import FilterCard

    column = str(clause.get("column") or "").strip()
    ensure_numeric_bounds(app, [column])
    bounds = getattr(app, "global_bounds", {}) or {}
    if column not in bounds:
        return f'"{column}" is not a numeric column, so it cannot be a range filter.'
    card = FilterCard(list(bounds.keys()), app, initial_property=column)
    card.set_filter_title(title)
    card.restore_state(column, float(clause["min"]), float(clause["max"]))
    card.restore_filter_flags(True, inverted)
    return card


def _text_card(app: Any, clause: dict[str, Any], title: str, inverted: bool) -> Any:
    from .filters.text_card import TextFilterCard

    column = str(clause.get("column") or "").strip()
    names = _filterable_columns(app)
    if column not in names:
        if column in list(getattr(app, "headers", None) or []):
            names = list(names) + [column]
        else:
            return f'Column "{column}" is not in the table.'
    if not names:
        return "No text columns are available to filter."
    card = TextFilterCard(names, app)
    card.set_filter_title(title)
    card.restore_from_session(
        column,
        str(clause.get("text") or ""),
        case_sensitive=bool(clause.get("case_sensitive", False)),
        partial_match=bool(clause.get("partial_match", True)),
    )
    card.restore_filter_flags(True, inverted)
    return card


def _substructure_card(app: Any, clause: dict[str, Any], title: str, inverted: bool) -> Any:
    from .filters.substructure_card import SubstructureFilterCard

    source = str(clause.get("structure_source") or "Structure").strip() or "Structure"
    sources = ["Structure"]
    getter = getattr(app, "chemistry_tool_structure_sources", None)
    if callable(getter):
        sources = list(getter() or sources)
    headers = list(getattr(app, "headers", None) or [])
    if source not in sources and source not in headers:
        return f'Structure source "{source}" is not in the table.'
    if source not in sources:
        sources = list(sources) + [source]
    card = SubstructureFilterCard(structure_sources=sources)
    card.set_filter_title(title)
    card.set_structure_source(source)
    card.set_smarts(str(clause.get("smarts") or ""))
    card.restore_filter_flags(True, inverted)
    return card


def _filterable_columns(app: Any) -> list[str]:
    getter = getattr(app, "_filterable_data_column_names", None)
    if callable(getter):
        return list(getter() or [])
    return [str(header) for header in (getattr(app, "headers", None) or []) if header]
