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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Shared table ↔ Plotly selection helpers (Plotter and PlotlyInteractiveView)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from .layout_perf import perf_span

if TYPE_CHECKING:
    from .main_window import ChemistryWorkspaceWindow


def visible_oids_for_plot(app: ChemistryWorkspaceWindow | None) -> frozenset[int] | None:
    """OIDs currently shown by table filters. ``None`` means every row is visible."""
    if app is None:
        return None
    fn = getattr(app, "_visible_oids_set", None)
    if not callable(fn):
        return None
    oids = fn()
    if oids is None:
        return None
    return frozenset(int(x) for x in oids)


def retained_snapshot_oids(
    app: ChemistryWorkspaceWindow | None,
    snapshot_oids: Iterable[int],
    *,
    respect_filters: bool = True,
) -> frozenset[int] | None:
    """OIDs from a stored plot that should still be drawn.

    ``None`` means every snapshot OID is still in the table and, when
    ``respect_filters`` is set, the current table filters are not hiding any of
    them. Otherwise the frozenset is the subset to keep, which may be empty.
    Analysis plots keep their computed points, so a row delete has to drop OIDs
    that are gone even when no filter is active (that case reports every
    remaining row as visible).
    """
    if app is None:
        return None
    snap: set[int] = set()
    for oid in snapshot_oids:
        try:
            snap.add(int(oid))
        except (TypeError, ValueError):
            continue
    if not snap:
        return None
    snap_fs = frozenset(snap)
    model = getattr(app, "_table_model", None)
    present_fn = getattr(model, "present_oids", None) if model is not None else None
    present = present_fn(snap_fs) if callable(present_fn) else snap_fs
    if respect_filters:
        visible = visible_oids_for_plot(app)
        if visible is not None:
            present = present & visible
    if len(present) == len(snap_fs):
        return None
    return present


def retained_pair_points(app: ChemistryWorkspaceWindow | None, points: Sequence) -> list:
    """Pair points whose both endpoints are still in the table and visible.

    Items expose ``oid_a`` and ``oid_b``. The input order is kept. When nothing
    is dropped, a copy of ``points`` is returned.
    """
    if not points:
        return []
    snap: list[int] = []
    for point in points:
        snap.append(int(point.oid_a))
        snap.append(int(point.oid_b))
    keep = retained_snapshot_oids(app, snap)
    if keep is None:
        return list(points)
    return [point for point in points if int(point.oid_a) in keep and int(point.oid_b) in keep]


def reindex_retained_point(previous: Sequence, points: Sequence, index: int | None) -> int | None:
    """Index of the previously current point after a filter or row delete, or None."""
    if index is None or not (0 <= int(index) < len(previous)):
        return None
    current = previous[int(index)]
    try:
        return points.index(current)
    except ValueError:
        return None


def selection_visual_push_key(indices: set[int] | frozenset[int]) -> tuple[int, int]:
    """Cheap dedupe key for plot selection restyles (avoids sorting large index sets)."""
    if not indices:
        return (0, 0)
    return (len(indices), hash(frozenset(indices)))


def run_javascript_apply_figure(page, payload_json: str) -> None:
    """Push a Plotly figure payload into the shell without double-encoding the JSON string."""
    # ``payload_json`` is already serialized; embed as a JS value (object or parseable).
    page.runJavaScript(f"window.molmanagerApply({payload_json});")


def run_javascript_set_selection(
    page, point_indices: list[int] | set[int] | frozenset[int]
) -> None:
    """Push selection indices as a JS array (``parseSelectionIndices`` accepts arrays)."""
    import json

    page.runJavaScript(f"window.molmanagerSetSelection({json.dumps(list(point_indices))});")


def selected_oids_for_plot(parent_app: ChemistryWorkspaceWindow) -> set[int]:
    """OIDs that should drive plot highlighting (the window's entry selection)."""
    return set(parent_app.selection_store.oids)


def build_oid_point_index(
    plotted_oids: list[int],
    partner_oids: list[int] | None = None,
) -> dict[int, list[int]]:
    """Map OID → point indices (includes optional pair-partner OIDs for the same index)."""
    index: dict[int, list[int]] = {}
    for i, oid in enumerate(plotted_oids):
        try:
            key = int(oid)
        except (TypeError, ValueError):
            continue
        index.setdefault(key, []).append(i)
    if partner_oids:
        for i, oid in enumerate(partner_oids):
            if i >= len(plotted_oids):
                break
            try:
                key = int(oid)
            except (TypeError, ValueError):
                continue
            bucket = index.setdefault(key, [])
            if i not in bucket:
                bucket.append(i)
    return index


def point_indices_for_oids(
    plotted_oids: list[int],
    selected_oids: set[int] | frozenset[int],
    *,
    oid_index: dict[int, list[int]] | None = None,
) -> set[int]:
    """Map table OIDs to scatter point indices for the current plot."""
    if not selected_oids:
        return set()
    if oid_index is not None:
        out: set[int] = set()
        for oid in selected_oids:
            try:
                key = int(oid)
            except (TypeError, ValueError):
                continue
            idxs = oid_index.get(key)
            if idxs:
                out.update(idxs)
        return out
    if not plotted_oids:
        return set()
    sel = selected_oids if isinstance(selected_oids, frozenset) else frozenset(selected_oids)
    return {i for i, oid in enumerate(plotted_oids) if int(oid) in sel}


def source_rows_for_point_indices(
    parent_app: ChemistryWorkspaceWindow,
    plotted_oids: list[int],
    point_indices: list[int],
    *,
    partner_oids: list[int] | None = None,
) -> list[int]:
    rows: list[int] = []
    n = len(plotted_oids)
    for idx in point_indices:
        if idx < 0 or idx >= n:
            continue
        for oid in (plotted_oids[idx],):
            row = parent_app.logical_row_for_oid(int(oid))
            if row >= 0:
                rows.append(int(row))
        if partner_oids is not None and idx < len(partner_oids):
            row = parent_app.logical_row_for_oid(int(partner_oids[idx]))
            if row >= 0:
                rows.append(int(row))
    return sorted(set(rows))


def _source_rows_already_selected(
    parent_app: ChemistryWorkspaceWindow, source_rows: list[int]
) -> bool:
    """True when the entry selection already holds exactly these source rows."""
    store = parent_app.selection_store
    if store.count() != len(source_rows):
        return False
    return parent_app._oids_for_source_rows(source_rows) == store.oids


def apply_table_selection_for_source_rows(
    parent_app: ChemistryWorkspaceWindow,
    source_rows: list[int],
    *,
    scroll: bool = True,
    focus: bool = True,
    origin: object = None,
) -> None:
    """Replace the entry selection with source-model rows picked in a plot (lasso / click).

    ``scroll`` reveals the first selected row in the table and centers it. ``focus`` also
    moves keyboard focus there; plot clicks pass ``False`` so Shift+select stays in the
    plot. ``origin`` is the plot, so its own ``selection_store.changed`` can be told apart
    from other writers. Re-applying the current selection is a no-op, which absorbs
    Plotly echo events.
    """
    if not source_rows:
        return
    uniq = sorted({int(r) for r in source_rows})
    with perf_span("selection.plot_to_table"):
        if _source_rows_already_selected(parent_app, uniq):
            return
        parent_app.select_table_rows(
            uniq,
            origin=origin,
            reveal=scroll,
            focus=bool(focus) and bool(scroll),
            center=bool(scroll),
        )


def clear_table_selection_from_plot(
    parent_app: ChemistryWorkspaceWindow, *, origin: object = None
) -> None:
    """Clear the entry selection when a plot deselects."""
    parent_app.clear_table_selection(origin=origin)
