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

"""Helpers for Plotly point hover cards (column text + structure thumbnail)."""

from __future__ import annotations

import base64
import html
from typing import Any

from ..chem.structure_2d_depiction import render_molecule_png

HOVER_THUMB_WIDTH = 140
HOVER_THUMB_HEIGHT = 116

_DEFAULT_HOVER_COLUMNS = (
    ("SMILES", "Name", "CompoundName", "ID"),
    ("Name", "CompoundName", "CAS", "InChIKey"),
    ("MW", "MolWt", "cLogP", "LogP", "TPSA"),
)


def default_hover_column_preferences() -> tuple[tuple[str, ...], ...]:
    return _DEFAULT_HOVER_COLUMNS


def hover_column_choices(headers: list[str] | None) -> list[str]:
    """Data columns suitable for hover labels (exclude id/structure)."""
    out: list[str] = []
    for h in headers or []:
        if not h or h in ("ID_HIDDEN", "Structure"):
            continue
        out.append(h)
    return out


def resolve_default_hover_columns(headers: list[str] | None, *, count: int = 3) -> list[str]:
    """Pick up to *count* default hover columns from table headers using preferences."""
    choices = hover_column_choices(headers)
    if not choices:
        return []
    chosen: list[str] = []
    used: set[str] = set()
    prefs = default_hover_column_preferences()
    for i in range(max(0, int(count))):
        prefer = prefs[i] if i < len(prefs) else ()
        pick = next((h for h in prefer if h in choices and h not in used), None)
        if pick is None:
            pick = next((h for h in choices if h not in used), None)
        if pick is None:
            break
        chosen.append(pick)
        used.add(pick)
    return chosen


def cell_text_for_oid(app: Any, oid: int, header: str) -> str:
    """Display text for *header* on the row with *oid*."""
    if app is None or not header:
        return ""
    try:
        row = app.logical_row_for_oid(int(oid))
    except Exception:
        return ""
    if row is None or row < 0:
        return ""
    model = getattr(app, "_table_model", None)
    if model is None:
        return ""
    try:
        raw = model.value_for_header(row, header)
        text = ("" if raw is None else str(raw)).strip()
        if text:
            return text
    except Exception:
        pass
    try:
        col = int(app.headers.index(header))
    except Exception:
        return ""
    try:
        cell_fn = getattr(app, "_table_cell_text", None)
        if callable(cell_fn):
            return (cell_fn(row, col) or "").strip()
        return (model.cell_text(row, col) or "").strip()
    except Exception:
        return ""


def hover_lines_for_oid(app: Any, oid: int, columns: list[str]) -> list[str]:
    """``Header: value`` lines for the selected hover columns."""
    lines: list[str] = []
    for h in columns:
        if not h:
            continue
        v = cell_text_for_oid(app, oid, h)
        if v == "":
            v = "—"
        lines.append(f"{h}: {v}")
    return lines


def structure_png_data_url_for_oid(
    app: Any,
    oid: int,
    *,
    width: int = HOVER_THUMB_WIDTH,
    height: int = HOVER_THUMB_HEIGHT,
) -> str:
    """Return a ``data:image/png;base64,…`` URL for *oid*, or ``\"\"`` if unavailable."""
    if app is None:
        return ""
    png: bytes | None = None
    model = getattr(app, "_table_model", None)
    if model is not None:
        try:
            stored = model.structure_png_bytes(int(oid))
            if stored:
                # Prefer a small dedicated render for hover size when a mol is available.
                png = stored
        except Exception:
            png = None
    mols = getattr(app, "mols", None)
    mol = None
    getter = getattr(mols, "get", None)
    if callable(getter):
        mol = getter(int(oid))
    if mol is not None:
        try:
            png = render_molecule_png(mol, int(width), int(height))
        except Exception:
            pass
    if not png:
        return ""
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"


HOVER_MULTI_MAX_ITEMS = 10
HOVER_MULTI_THUMB_WIDTH = 96
HOVER_MULTI_THUMB_HEIGHT = 80


def hover_card_payload(
    app: Any,
    oid: int,
    columns: list[str],
    *,
    show_structure: bool,
    x_label: str = "",
    y_label: str = "",
    x_value: Any = None,
    y_value: Any = None,
    z_label: str = "",
    z_value: Any = None,
    thumb_width: int = HOVER_THUMB_WIDTH,
    thumb_height: int = HOVER_THUMB_HEIGHT,
) -> dict[str, Any]:
    """JSON-serializable hover card content for one point."""
    lines = hover_lines_for_oid(app, oid, columns)
    coord_bits: list[str] = []
    if x_label and x_value is not None:
        coord_bits.append(f"{x_label}={x_value}")
    if y_label and y_value is not None:
        coord_bits.append(f"{y_label}={y_value}")
    if z_label and z_value is not None:
        coord_bits.append(f"{z_label}={z_value}")
    if coord_bits:
        lines.insert(0, ", ".join(coord_bits))
    img = (
        structure_png_data_url_for_oid(app, oid, width=thumb_width, height=thumb_height)
        if show_structure
        else ""
    )
    safe_lines = [html.escape(s) for s in lines]
    return {
        "oid": int(oid),
        "lines": lines,
        "html_lines": safe_lines,
        "img": img,
    }


def hover_cards_payload(
    app: Any,
    oids: list[int],
    columns: list[str],
    *,
    show_structure: bool,
    max_items: int = HOVER_MULTI_MAX_ITEMS,
) -> dict[str, Any]:
    """Hover overlay payload for one or many selected/hovered points.

    Caps rendered cards at ``max_items`` (default 10) and reports overflow so the
    UI can show “… and N more” without slowing large selections.
    """
    clean: list[int] = []
    seen: set[int] = set()
    for raw in oids:
        try:
            oid = int(raw)
        except Exception:
            continue
        if oid in seen:
            continue
        seen.add(oid)
        clean.append(oid)
    total = len(clean)
    if total == 0:
        return {"count": 0, "items": [], "title": "", "overflow": 0}
    if total == 1:
        one = hover_card_payload(app, clean[0], columns, show_structure=show_structure)
        return {
            "count": 1,
            "items": [one],
            "title": "",
            "overflow": 0,
            # Back-compat for single-card JS path
            "oid": one["oid"],
            "lines": one["lines"],
            "html_lines": one["html_lines"],
            "img": one["img"],
        }
    limit = max(1, int(max_items))
    shown = clean[:limit]
    overflow = max(0, total - len(shown))
    compact = total > 1
    tw = HOVER_MULTI_THUMB_WIDTH if compact else HOVER_THUMB_WIDTH
    th = HOVER_MULTI_THUMB_HEIGHT if compact else HOVER_THUMB_HEIGHT
    items = [
        hover_card_payload(
            app,
            oid,
            columns,
            show_structure=show_structure,
            thumb_width=tw,
            thumb_height=th,
        )
        for oid in shown
    ]
    title = f"{total} selected"
    if overflow:
        title = f"{total} selected · showing {len(shown)}"
    return {
        "count": total,
        "items": items,
        "title": title,
        "overflow": overflow,
    }
