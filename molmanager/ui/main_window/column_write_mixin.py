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

"""Shared table column naming, inserts, and chemistry-tool writeback."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ..chunked_table_write import ChunkedTableWriter
from ..widgets import CategoryFilterCard, FilterCard, TextFilterCard

# Keep filling these headers in place even when the selected cells already have values.
_ALWAYS_REUSE_COLUMNS = frozenset({"pKa", "pI"})
_UNCALCULATED_CELL_VALUES = frozenset({"", "n/a", "cancelled", "cancelled."})


def cell_looks_uncalculated(text: str) -> bool:
    """True for blank, ``N/A``, cancel, or error placeholders a later run may fill."""
    t = (text or "").strip().lower()
    if t in _UNCALCULATED_CELL_VALUES:
        return True
    return t.startswith("error")


class ColumnWriteMixin:
    def _unique_table_column_names(self, bases: list[str]) -> list[str]:
        """Return column header names; append `` (n)`` when a name already exists in the table."""
        return self._result_column_names(bases, result_oids=None)

    def _column_has_uncalculated_oids(self, header: str, oids: Sequence[int]) -> bool:
        """True when *header* is missing or any of *oids* still has a fillable cell."""
        if header not in self.headers:
            return True
        model = getattr(self, "_table_model", None)
        row_of = getattr(model, "logical_row_for_oid", None)
        if model is None or not callable(row_of):
            return False
        backing = getattr(model, "backing_value_for_row_header", None)
        value_of = getattr(model, "value_for_header", None)
        for oid in oids:
            try:
                row = int(row_of(int(oid)))
            except (TypeError, ValueError):
                return True
            if row < 0:
                return True
            if callable(backing):
                text = str(backing(row, header) or "")
            elif callable(value_of):
                text = str(value_of(row, header) or "")
            else:
                return False
            if cell_looks_uncalculated(text):
                return True
        return False

    def _result_column_names(
        self, bases: list[str], result_oids: Sequence[int] | None = None
    ) -> list[str]:
        """Choose write headers, reusing an existing column when filling uncalculated cells.

        ``pKa`` / ``pI`` always update in place. Other names reuse the existing
        header when any of *result_oids* is still blank / ``N/A`` / cancelled /
        error in that column, so a cancelled job can finish without splitting
        ``confs`` and similar results across suffixed copies.
        Otherwise a `` (n)`` suffix is added so filled cells are not replaced.
        """
        oids = [int(oid) for oid in (result_oids or ()) if oid is not None]
        out: list[str] = []
        used = set(self.headers)
        assigned: set[str] = set()
        for raw in bases:
            base = (raw or "").strip() or "Column"
            reuse = base in _ALWAYS_REUSE_COLUMNS or base not in used
            if not reuse and oids:
                reuse = self._column_has_uncalculated_oids(base, oids)
            if reuse and base not in assigned:
                col = base
            else:
                col = base
                if col in used:
                    cnt = 1
                    while f"{base} ({cnt})" in used:
                        cnt += 1
                    col = f"{base} ({cnt})"
            out.append(col)
            used.add(col)
            assigned.add(col)
        return out

    def _ensure_columns(self, col_names: list[str]) -> None:
        """Ensure the table has these headers (adds columns to the right if needed)."""
        if not self.headers:
            self.headers = ["ID_HIDDEN", "Structure", "SMILES"]
            self._table_model.set_headers(list(self.headers))
            self.table.setColumnHidden(0, True)
        existing = {h: i for i, h in enumerate(self.headers)}
        to_add = [h for h in col_names if h not in existing]
        if to_add:
            col_at = len(self.headers)
            self.headers.extend(to_add)
            self._table_model.insert_columns_at(col_at, to_add, None)

    def _sync_global_bounds_for_headers(
        self, headers: list[str], *, refresh_filters: bool = False
    ) -> None:
        """Refresh slider min/max for specific columns without scanning the whole table."""
        if not headers:
            return
        self._table_model.refresh_numeric_bounds_for_headers(headers)
        cache = self._table_model._numeric_bounds_cache
        if cache is not None:
            for h in headers:
                if h in cache:
                    self.global_bounds[h] = cache[h]
                else:
                    self.global_bounds.pop(h, None)
        if refresh_filters:
            cols = self._filterable_data_column_names()
            for f in self.filters:
                if isinstance(f, FilterCard):
                    f.update_prop_list(list(self.global_bounds.keys()))
                elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
                    f.update_prop_list(cols)
        self._refresh_active_plot_axis_columns()
        refresh_search = getattr(self, "_refresh_table_search_column_combos", None)
        if callable(refresh_search):
            refresh_search()

    def _calc_writeback_async_min_rows(self) -> int:
        from ...platform_support.config import load_config

        return max(500, int(load_config().tool_table_chunk_rows))

    def _calc_writeback_chunk_rows(self) -> int:
        from ...platform_support.config import load_config

        cfg = load_config()
        return max(250, min(int(cfg.ingest_gui_chunk_size), int(cfg.tool_table_chunk_rows)))

    def _apply_calc_bulk_rows(
        self, calc_h: list[str], bulk_rows: list[tuple[int, dict[str, str]]]
    ) -> None:
        if not bulk_rows:
            return
        if len(calc_h) == 1:
            hdr = calc_h[0]
            self._table_model.set_column_text_by_oids(
                hdr,
                [(oid, values[hdr]) for oid, values in bulk_rows],
            )
            return
        self._table_model.apply_columns_values_bulk(calc_h, bulk_rows)

    def _finalize_calc_writeback(
        self,
        calc_h: list[str],
        new_h: list[str],
        *,
        on_complete: Callable[[list[str]], None] | None = None,
    ) -> None:
        if self._table_model.rowCount() >= 5000:
            dirty = {h for h in calc_h if h in self._table_model._bounds_data_headers()}
            if dirty:
                self._table_model._mark_numeric_bounds_dirty(dirty)
            self.schedule_calculate_global_bounds()
        else:
            self._sync_global_bounds_for_headers(calc_h, refresh_filters=bool(new_h))
        for header_name in calc_h:
            self._table_model.apply_favorable_score_column_coloring(header_name)
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        self.status_label.setText(self._consume_partial_results_notice() or "Done.")
        if on_complete is not None:
            on_complete(list(calc_h))

    def _start_calc_writeback(
        self,
        calc_h: list[str],
        new_h: list[str],
        bulk_rows: list[tuple[int, dict[str, str]]],
        *,
        on_complete: Callable[[list[str]], None] | None = None,
    ) -> None:
        """Apply result rows in GUI-budgeted chunks, yielding between each one."""

        def write_chunk(start: int, end: int, _is_last: bool) -> None:
            self._apply_calc_bulk_rows(calc_h, bulk_rows[start:end])

        def on_progress(done: int, total: int) -> None:
            on_prog = getattr(self, "_on_tool_progress", None)
            if callable(on_prog):
                on_prog("Writing results…", done, total)
            else:
                self.status_label.setText(f"Writing results… ({done:,}/{total:,})")

        def on_done() -> None:
            self._calc_writer = None
            finish = getattr(self, "_finish_tool_progress", None)
            if callable(finish):
                finish("Writing results", status_message=None)
            self._finalize_calc_writeback(calc_h, new_h, on_complete=on_complete)

        writer = getattr(self, "_calc_writer", None)
        if writer is not None:
            writer.cancel()
        self._calc_writer = ChunkedTableWriter(
            table=self.table,
            total=len(bulk_rows),
            chunk=self._calc_writeback_chunk_rows(),
            write_chunk=write_chunk,
            on_progress=on_progress,
            on_done=on_done,
        )
        self._calc_writer.start()

    def on_calc_finished(
        self,
        res,
        calc_h,
        *,
        finish_progress: bool = True,
        progress_label: str | None = None,
        on_complete: Callable[[list[str]], None] | None = None,
    ) -> list[str]:
        """Write tool results into the table, adding columns as needed.

        Existing headers are reused when any incoming row is still uncalculated
        in that column (blank / ``N/A`` / cancelled / error), so a cancelled run
        can finish without splitting results. Filled cells keep their column:
        colliding names become ``Name (1)``, ``Name (2)``, … via
        :meth:`_result_column_names`. ``pKa`` and ``pI`` always update in place.
        ``pI`` is only written when Predict pKa is run with isoelectric point enabled.
        Returns the final header list written. Large result sets are applied in
        GUI-budgeted chunks; ``on_complete`` runs after values (and coloring) land.
        """
        calc_h = [str(h) for h in (calc_h or [])]
        if not calc_h:
            if finish_progress:
                self._finish_tool_progress(progress_label, status_message=None)
            self.status_label.setText(self._consume_partial_results_notice() or "Done.")
            if on_complete is not None:
                on_complete([])
            return []

        result_oids = [int(oid) for oid, _row in res if oid is not None]
        unique_h = self._result_column_names(calc_h, result_oids)
        rename = {old: new for old, new in zip(calc_h, unique_h) if old != new}
        calc_h = list(unique_h)
        if rename:
            remapped: list[tuple[int, dict]] = []
            for oid, row_d in res:
                row_d = row_d or {}
                remapped.append(
                    (
                        int(oid),
                        {rename.get(str(k), str(k)): v for k, v in row_d.items()},
                    )
                )
            res = remapped

        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        h_map = {h: i for i, h in enumerate(self.headers)}
        new_h = [h for h in calc_h if h not in h_map]
        if new_h:
            col_at = len(self.headers)
            self.headers.extend(new_h)
            self._table_model.insert_columns_at(col_at, new_h, None)
        bulk_rows = [
            (int(oid), {h: str(row_d.get(h, "N/A")) for h in calc_h}) for oid, row_d in res
        ]
        async_min = self._calc_writeback_async_min_rows()
        if bulk_rows and len(bulk_rows) >= async_min:
            begin = getattr(self, "_begin_tool_progress", None)
            if callable(begin):
                begin("Writing results", len(bulk_rows))
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            self._start_calc_writeback(
                list(calc_h), list(new_h), bulk_rows, on_complete=on_complete
            )
            return list(calc_h)

        if finish_progress:
            self._finish_tool_progress(progress_label, status_message=None)
        try:
            self._apply_calc_bulk_rows(calc_h, bulk_rows)
            self._finalize_calc_writeback(calc_h, new_h, on_complete=on_complete)
        except Exception:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            raise
        return list(calc_h)
