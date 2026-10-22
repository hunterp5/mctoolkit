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

"""Read the main compound table into pandas for analysis tools.

These helpers used to live in the Statistics dialog module. QSAR, MMP,
dimensionality reduction, and medchem-space only needed a DataFrame, so
importing them from there also constructed the six-tab Statistics UI.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from .main_window import ChemistryWorkspaceWindow

__all__ = [
    "iter_scoped_table_analysis_rows",
    "numeric_subset",
    "scoped_table_analysis_row_indices",
    "scoped_table_column_names",
    "selected_table_column_headers",
    "table_to_dataframe",
]


def scoped_table_analysis_row_indices(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> list[int]:
    """Source-model row indices included in analysis scope, in table order."""
    m = app._table_model
    if not app.headers or m.columnCount() < 1 or m.rowCount() < 1:
        return []

    selected_oids: set[int] = app._selected_oids_set() if only_selected else set()

    visible_rows: set[int] | None = None
    if visible_only:
        vis = app._visible_source_row_indices()
        visible_rows = None if vis is None else set(vis)

    out: list[int] = []
    for r in range(m.rowCount()):
        if visible_rows is not None and r not in visible_rows:
            continue
        if only_selected:
            t0 = m.cell_text(r, 0)
            if not t0.isdigit() or int(t0) not in selected_oids:
                continue
        out.append(r)
    return out


def iter_scoped_table_analysis_rows(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield (table_row_index, row_dict) for rows included in analysis scope."""
    m = app._table_model
    ncols = m.columnCount()
    for r in scoped_table_analysis_row_indices(
        app, visible_only=visible_only, only_selected=only_selected
    ):
        row: dict[str, str] = {}
        for c in range(ncols):
            if c >= len(app.headers):
                break
            name = app.headers[c]
            if name == "Structure":
                continue
            text = (m.cell_text(r, c) or "").strip()
            if not text:
                text = (m.backing_value_for_row_header(r, name) or "").strip()
            row[name] = text
        yield r, row


def table_to_dataframe(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> tuple[pd.DataFrame, list[int]]:
    """Build a DataFrame from the main table (skips Structure) and parallel source row indices."""
    import pandas as pd

    bulk = getattr(app._table_model, "analysis_column_texts", None)
    if callable(bulk):
        source_rows = scoped_table_analysis_row_indices(
            app, visible_only=visible_only, only_selected=only_selected
        )
        if not source_rows:
            return pd.DataFrame(), []
        return pd.DataFrame(bulk(list(app.headers), source_rows), copy=False), source_rows

    rows: list[dict[str, str]] = []
    source_rows = []
    for r, row in iter_scoped_table_analysis_rows(
        app, visible_only=visible_only, only_selected=only_selected
    ):
        source_rows.append(r)
        rows.append(row)
    return pd.DataFrame(rows), source_rows


def scoped_table_column_names(
    app: ChemistryWorkspaceWindow,
    *,
    visible_only: bool = True,
    only_selected: bool = False,
) -> tuple[list[str], list[str]]:
    """Return ``(all_columns, numeric_columns)`` for the analysis scope.

    Same names :func:`table_to_dataframe` and :func:`numeric_subset` would produce, but column
    pickers never look at the values, so whole-table scope answers straight from the model's
    numeric-bounds cache instead of materializing every cell.
    """
    m = app._table_model
    bulk = getattr(m, "analysis_column_texts", None)
    bounds = getattr(m, "numeric_bounds_by_column", None)
    scoped_rows = None if only_selected else app._visible_source_row_indices()
    whole_table = not only_selected and (not visible_only or scoped_rows is None)
    if whole_table and callable(bulk) and callable(bounds) and app.headers and m.rowCount() >= 1:
        names = list(bulk(list(app.headers), []))
        numeric_headers = bounds()
        return names, [h for h in names if h != "ID_HIDDEN" and h in numeric_headers]

    df, _rows = table_to_dataframe(app, visible_only=visible_only, only_selected=only_selected)
    return list(df.columns), list(numeric_subset(df, exclude_id=True).columns)


def selected_table_column_headers(app: ChemistryWorkspaceWindow) -> list[str]:
    """Distinct data-column header names currently spanned by the main-table selection."""
    sm = app.table.selectionModel()
    if sm is None or not app.headers:
        return []
    view_cols = sorted({ix.column() for ix in sm.selectedIndexes() if ix.isValid()})
    names: list[str] = []
    for col in view_cols:
        if col <= 0 or col >= len(app.headers):
            continue
        name = app.headers[col]
        if name in ("ID_HIDDEN", "Structure"):
            continue
        if name not in names:
            names.append(name)
    return names


def numeric_subset(df: pd.DataFrame, *, exclude_id: bool = True) -> pd.DataFrame:
    """Columns that have at least one finite numeric value; optionally drop ID_HIDDEN."""
    import pandas as pd

    if df.empty:
        return df
    cols = [c for c in df.columns if not (exclude_id and c == "ID_HIDDEN")]
    num = df[cols].apply(pd.to_numeric, errors="coerce")
    keep = [c for c in num.columns if num[c].notna().any()]
    return num[keep] if keep else pd.DataFrame(index=df.index)
