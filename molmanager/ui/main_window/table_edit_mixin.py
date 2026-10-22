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

"""Clipboard edit and chunked delete/clear for the main table."""

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox
from rdkit import Chem

from ...platform_support.config import load_config
from ...chem.molecule_conversion import looks_like_mol_block, mol_to_canonical_smiles
from ..compound_table_model import CompoundTableModel
from ..table_clipboard import format_tsv_grid, parse_tsv_grid, tsv_grid_is_block
from .table_undo_commands import (
    DeleteRowSnapshot,
    UndoClearCellsCommand,
    UndoDeleteColumnCommand,
    UndoDeleteRowsCommand,
    UndoPasteBlockCommand,
    UndoPasteCellCommand,
    depiction_column_for_cell,
)


class TableEditMixin:
    """Copy/paste, selection delete, and clear-cells workflows."""

    def _copy_text_for_table_cell(self, row: int, col: int, oid: int | None) -> tuple[bool, str]:
        """Whether copy is meaningful, and the string to place on the clipboard."""
        if oid is None:
            return False, ""
        if col == 0:
            return True, str(oid)
        if col == CompoundTableModel.STRUCTURE_COL:
            if "SMILES" in self.headers:
                sci = self.headers.index("SMILES")
                t = (self._table_model.cell_text(row, sci) or "").strip()
                if t:
                    return True, t
            mol = self.mols.get(oid)
            if mol is not None:
                try:
                    return True, mol_to_canonical_smiles(mol)
                except Exception:
                    return False, ""
            return False, ""
        h = self.headers[col] if 0 <= col < len(self.headers) else ""
        if h and self._table_model.is_pixmap_data_column(h):
            t = (self._table_model.backing_value_for_row_header(row, h) or "").strip()
            return (True, t) if t else (False, "")
        if self._table_model.column_accepts_text_edit(col):
            return True, self._table_model.cell_text(row, col) or ""
        return False, ""

    def _source_cell_from_view_index(self, ix) -> tuple[int, int] | None:
        """Map a table-view index to ``(source_row, source_col)``."""
        if ix is None or not ix.isValid():
            return None
        proxy = getattr(self, "_filter_proxy_model", None)
        if proxy is not None and self.table.model() is proxy:
            sidx = proxy.mapToSource(ix)
            if not sidx.isValid():
                return None
            return int(sidx.row()), int(sidx.column())
        return int(ix.row()), int(ix.column())

    def _paste_origin_source_cell(self) -> tuple[int, int] | None:
        """Top-left source cell of the current selection (or the current index)."""
        cells = self._selected_source_cells()
        if not cells:
            mapped = self._source_cell_from_view_index(self.table.currentIndex())
            if mapped is not None:
                cells.append(mapped)
        if not cells:
            return None
        return min(r for r, _c in cells), min(c for _r, c in cells)

    def _oid_for_source_row(self, row: int) -> int | None:
        t0 = self._table_model.cell_text(row, 0)
        return int(t0) if t0.isdigit() else None

    def _selected_source_cells(self) -> list[tuple[int, int]]:
        """Source cells of selected Qt cells plus every shown cell of the selected entries."""
        cells: list[tuple[int, int]] = []
        sm = self.table.selectionModel()
        if sm is not None:
            for ix in sm.selectedIndexes():
                mapped = self._source_cell_from_view_index(ix)
                if mapped is not None:
                    cells.append(mapped)
        cells.extend(self._selected_entry_source_cells())
        return cells

    def edit_copy(self) -> None:
        """Copy the current selection to the clipboard (tab-separated columns, newline-separated rows)."""
        source_cells = self._selected_source_cells()
        if not source_cells:
            mapped = self._source_cell_from_view_index(self.table.currentIndex())
            if mapped is not None:
                source_cells = [mapped]
        if not source_cells:
            self.status_label.setText("Copy: nothing selected.")
            return
        cells: dict[tuple[int, int], str] = {}
        for row, col in source_cells:
            if (row, col) in cells or col == 0:
                continue
            oid = self._oid_for_source_row(row)
            ok, txt = self._copy_text_for_table_cell(row, col, oid)
            cells[(row, col)] = txt if ok else ""
        if not cells:
            self.status_label.setText("Copy: no copyable text in the selection.")
            return
        row_ids = sorted({r for r, _c in cells})
        col_ids = sorted({c for _r, c in cells})
        grid = [[cells.get((r, c), "") for c in col_ids] for r in row_ids]
        text = format_tsv_grid(grid)
        if not text.strip():
            self.status_label.setText("Copy: no copyable text in the selection.")
            return
        QApplication.clipboard().setText(text)
        n_r, n_c = len(grid), len(grid[0])
        if n_r == 1 and n_c == 1:
            self.status_label.setText("Copy: copied selection to clipboard.")
        else:
            self.status_label.setText(f"Copy: copied {n_r}×{n_c} cells.")

    def edit_paste(
        self,
        *,
        origin: tuple[int, int] | None = None,
        block_mode: str | None = None,
        overwrite: bool | None = None,
    ) -> None:
        """Paste clipboard text into the selected cell, or a block from its top-left."""
        if origin is None:
            origin = self._paste_origin_source_cell()
        if origin is None:
            self.status_label.setText("Paste: select a cell first.")
            return
        row, col = origin
        oid = self._oid_for_source_row(row)
        if oid is None:
            self.status_label.setText("Paste: invalid row.")
            return
        clip = QApplication.clipboard().text() or ""
        if not clip.strip():
            QMessageBox.information(self, "Paste", "Clipboard is empty.")
            return
        grid = parse_tsv_grid(clip)
        is_block = tsv_grid_is_block(grid) and not looks_like_mol_block(clip)
        if not is_block:
            self._paste_single_cell(row, col, oid, clip.strip())
            return
        mode = block_mode
        if mode not in ("single", "multi"):
            mode = self._ask_paste_block_mode(len(grid), len(grid[0]))
        if mode is None:
            return
        if mode == "single":
            self._paste_single_cell(row, col, oid, clip.strip())
            return
        writes, n_clipped, n_skipped, n_overwrite = self._plan_block_paste(row, col, grid)
        if not writes:
            extra = []
            if n_clipped:
                extra.append(f"{n_clipped:,} outside the table")
            if n_skipped:
                extra.append(f"{n_skipped:,} not editable")
            suffix = f" ({'; '.join(extra)})" if extra else ""
            self.status_label.setText(f"Paste: nothing written{suffix}.")
            return
        proceed = overwrite
        if proceed is None and n_overwrite:
            proceed = self._confirm_paste_overwrite(n_overwrite, n_clipped)
        elif proceed is None:
            proceed = True
        if not proceed:
            self.status_label.setText("Paste: cancelled.")
            return
        self._undo_stack.push(UndoPasteBlockCommand(self, writes))
        n = len(writes)
        parts = [f"Paste: filled {n:,} cell(s)."]
        if n_overwrite:
            parts.append(f"Overwrote {n_overwrite:,}.")
        if n_clipped:
            parts.append(f"{n_clipped:,} outside the table.")
        if n_skipped:
            parts.append(f"{n_skipped:,} skipped.")
        self.status_label.setText(" ".join(parts))

    def _paste_single_cell(self, row: int, col: int, oid: int, clip: str) -> None:
        if not self._column_accepts_cell_paste(row, col):
            self.status_label.setText("Paste: this column cannot be edited.")
            return
        if col == CompoundTableModel.STRUCTURE_COL or (
            0 <= col < len(self.headers)
            and self._table_model.is_pixmap_data_column(self.headers[col])
        ):
            if self._mol_from_structure_text(clip) is None:
                QMessageBox.warning(
                    self,
                    "Paste",
                    "Could not interpret the clipboard as a structure (try SMILES, InChI, or a MolBlock).",
                )
                return
        self._undo_stack.push(UndoPasteCellCommand(self, row, col, oid, clip))

    def _ask_paste_block_mode(self, n_rows: int, n_cols: int) -> str | None:
        """Ask whether a multi-cell clipboard should fill one cell or a block."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Paste")
        box.setText(
            f"The clipboard contains a {n_rows}×{n_cols} block of cells.\n\n"
            "Paste everything into the selected cell, or fill multiple cells "
            "starting at the top-left of the selection?"
        )
        single_btn = box.addButton("This cell only", QMessageBox.AcceptRole)
        multi_btn = box.addButton("Multiple cells", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(multi_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is single_btn:
            return "single"
        if clicked is multi_btn:
            return "multi"
        return None

    def _confirm_paste_overwrite(self, n_overwrite: int, n_clipped: int) -> bool:
        extra = ""
        if n_clipped:
            extra = (
                f"\n\n{n_clipped:,} clipboard cell(s) fall outside the table and will be skipped."
            )
        reply = QMessageBox.warning(
            self,
            "Paste",
            f"This paste will overwrite {n_overwrite:,} cell(s) that already have values.{extra}\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _block_paste_dest_rows(self, start_row: int, n: int) -> list[int]:
        rows: list[int] = []
        for r in self._iter_visible_source_row_indices():
            if r < start_row:
                continue
            rows.append(int(r))
            if len(rows) >= n:
                break
        return rows

    def _block_paste_dest_cols(self, start_col: int, n: int) -> list[int]:
        cols: list[int] = []
        for c in range(max(int(start_col), 1), len(self.headers)):
            cols.append(c)
            if len(cols) >= n:
                break
        return cols

    def _cell_is_populated_for_paste(self, row: int, col: int, oid: int) -> bool:
        if col == CompoundTableModel.STRUCTURE_COL:
            return self.mols.get(oid) is not None
        if col <= 0 or col >= len(self.headers):
            return False
        h = self.headers[col]
        return bool((self._table_model.backing_value_for_row_header(row, h) or "").strip())

    def _plan_block_paste(
        self, origin_row: int, origin_col: int, grid: list[list[str]]
    ) -> tuple[list[tuple[int, int, int, str]], int, int, int]:
        """Map a clipboard grid onto the table from ``origin``. Returns writes and skip counts."""
        n_rows = len(grid)
        n_cols = len(grid[0]) if grid else 0
        dest_rows = self._block_paste_dest_rows(origin_row, n_rows)
        dest_cols = self._block_paste_dest_cols(origin_col, n_cols)
        writes: list[tuple[int, int, int, str]] = []
        n_clipped = 0
        n_skipped = 0
        n_overwrite = 0
        for i, src_row in enumerate(grid):
            if i >= len(dest_rows):
                n_clipped += len(src_row)
                continue
            drow = dest_rows[i]
            oid = self._oid_for_source_row(drow)
            if oid is None:
                n_skipped += len(src_row)
                continue
            for j, text in enumerate(src_row):
                if j >= len(dest_cols):
                    n_clipped += 1
                    continue
                dcol = dest_cols[j]
                if not self._column_accepts_cell_paste(drow, dcol):
                    n_skipped += 1
                    continue
                is_struct = dcol == CompoundTableModel.STRUCTURE_COL or (
                    0 <= dcol < len(self.headers)
                    and self._table_model.is_pixmap_data_column(self.headers[dcol])
                )
                if is_struct and self._mol_from_structure_text(text) is None:
                    n_skipped += 1
                    continue
                if self._cell_is_populated_for_paste(drow, dcol, oid):
                    n_overwrite += 1
                writes.append((drow, dcol, oid, text))
        return writes, n_clipped, n_skipped, n_overwrite

    def _cancel_chunked_table_delete(self) -> None:
        self._table_delete_job_gen = int(getattr(self, "_table_delete_job_gen", 0)) + 1
        self._table_delete_ctx = None

    def _selected_full_column_indices(self) -> list[int]:
        """Source-model columns where every visible row is selected (full-column select)."""
        sm = self.table.selectionModel()
        view_model = self.table.model()
        if sm is None or view_model is None:
            return []
        proxy = getattr(self, "_filter_proxy_model", None)
        use_proxy = proxy is not None and view_model is proxy
        cols: list[int] = []
        seen: set[int] = set()
        for ix in sm.selectedColumns():
            if not ix.isValid():
                continue
            if use_proxy:
                sidx = proxy.mapToSource(view_model.index(ix.row(), ix.column()))
                col = int(sidx.column()) if sidx.isValid() else int(ix.column())
            else:
                col = int(ix.column())
            if col <= 0 or col >= len(self.headers) or col in seen:
                continue
            seen.add(col)
            cols.append(col)
        return cols

    def _has_full_row_selection(self) -> bool:
        return not self.selection_store.is_empty()

    def _selected_clearable_cells(self) -> list[tuple[int, str, str]]:
        """``(oid, header, old_text)`` for selected text cells that currently have a value."""
        sm = self.table.selectionModel()
        view_model = self.table.model()
        if sm is None or view_model is None:
            return []
        proxy = getattr(self, "_filter_proxy_model", None)
        use_proxy = proxy is not None and view_model is proxy
        out: list[tuple[int, str, str]] = []
        seen: set[tuple[int, str]] = set()
        model = self._table_model
        for ix in sm.selectedIndexes():
            if not ix.isValid():
                continue
            if use_proxy:
                sidx = proxy.mapToSource(ix)
                if not sidx.isValid():
                    continue
                row, col = int(sidx.row()), int(sidx.column())
            else:
                row, col = int(ix.row()), int(ix.column())
            if not model.column_accepts_text_edit(col):
                continue
            header = self.headers[col]
            t0 = model.cell_text(row, 0)
            if not t0.isdigit():
                continue
            oid = int(t0)
            key = (oid, header)
            if key in seen:
                continue
            seen.add(key)
            old = model.cell_text(row, col) or ""
            if old == "":
                continue
            out.append((oid, header, old))
        return out

    def _delete_selection_kind(self) -> str:
        """``rows``, ``columns``, ``cells``, ``both``, or ``empty`` for Edit → Delete Selection."""
        has_rows = self._has_full_row_selection()
        has_cols = bool(self._selected_full_column_indices())
        if has_rows and has_cols:
            return "both"
        if has_rows:
            return "rows"
        if has_cols:
            return "columns"
        sm = self.table.selectionModel()
        if sm is not None and any(ix.isValid() for ix in sm.selectedIndexes()):
            return "cells"
        return "empty"

    def _ask_delete_rows_or_columns(self, n_rows: int, col_names: list[str]) -> str | None:
        """Prompt when both rows and columns are selected. Returns ``rows``, ``columns``, or None."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Delete Selection")
        n_cols = len(col_names)
        box.setText("Both rows and columns are selected. What should be deleted?")
        shown = ", ".join(col_names[:8])
        if n_cols > 8:
            shown += f", … ({n_cols:,} columns)"
        box.setInformativeText(
            f"{n_rows:,} selected row(s); {n_cols:,} selected column(s)"
            + (f" ({shown})." if shown else ".")
        )
        rows_btn = box.addButton(
            f"Delete {n_rows:,} row(s)",
            QMessageBox.AcceptRole,
        )
        cols_btn = box.addButton(
            f"Delete {n_cols:,} column(s)",
            QMessageBox.DestructiveRole,
        )
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(box.button(QMessageBox.Cancel))
        box.exec_()
        clicked = box.clickedButton()
        if clicked is rows_btn:
            return "rows"
        if clicked is cols_btn:
            return "columns"
        return None

    def _confirm_and_push_delete_columns(self, cols: list[int]) -> None:
        """Confirm then delete selected data columns (not ID or Structure)."""
        names = []
        skipped: list[str] = []
        for col in cols:
            if col < 0 or col >= len(self.headers):
                continue
            hdr = self.headers[col]
            if hdr in ("ID_HIDDEN", "Structure"):
                skipped.append(hdr)
                continue
            names.append(hdr)
        # Preserve first-seen order while dropping duplicates.
        unique_names: list[str] = []
        seen: set[str] = set()
        for hdr in names:
            if hdr in seen:
                continue
            seen.add(hdr)
            unique_names.append(hdr)
        if not unique_names:
            if skipped:
                QMessageBox.information(
                    self,
                    "Delete Selection",
                    "The Structure column cannot be deleted.",
                )
            else:
                QMessageBox.information(self, "Delete Selection", "No columns selected.")
            return
        n = len(unique_names)
        shown = ", ".join(f"'{h}'" for h in unique_names[:8])
        if n > 8:
            shown += f", … ({n:,} columns)"
        extra = ""
        if skipped:
            extra = " The Structure column will be kept."
        msg = (
            f"Delete column {shown}? This cannot be undone except with Edit → Undo.{extra}"
            if n == 1
            else f"Delete {n:,} selected columns ({shown})? "
            f"This cannot be undone except with Edit → Undo.{extra}"
        )
        reply = QMessageBox.question(
            self,
            "Delete Selection",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        label = f"Delete {n} column(s)" if n != 1 else f"Delete column '{unique_names[0]}'"
        self._undo_stack.beginMacro(label)
        try:
            for hdr in unique_names:
                try:
                    idx = self.headers.index(hdr)
                except ValueError:
                    continue
                self._undo_stack.push(UndoDeleteColumnCommand(self, idx))
        finally:
            self._undo_stack.endMacro()

    def _confirm_and_push_clear_cells(self) -> None:
        changes = self._selected_clearable_cells()
        if not changes:
            QMessageBox.information(
                self,
                "Delete Selection",
                "No cell values to delete. Structure and image columns cannot be cleared this way.",
            )
            return
        n = len(changes)
        msg = (
            "Delete the data in this cell? This cannot be undone except with Edit → Undo."
            if n == 1
            else f"Delete data from {n:,} selected cells? "
            "This cannot be undone except with Edit → Undo."
        )
        reply = QMessageBox.question(
            self,
            "Delete Selection",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._undo_stack.push(UndoClearCellsCommand(self, changes))

    def _confirm_and_push_delete_rows(
        self, rows: list[int] | None = None, *, oids: frozenset[int] | None = None
    ) -> None:
        """Confirm then push UndoDeleteRowsCommand (shared by Edit and row header menu)."""
        if oids is None:
            rows = sorted({int(r) for r in (rows or [])})
            if not rows:
                QMessageBox.information(self, "Delete Selection", "No rows selected.")
                return
            oids = self._oids_for_row_indices(rows)
        n = len(oids)
        if n <= 0:
            QMessageBox.information(self, "Delete Selection", "No rows selected.")
            return
        title = "Delete Row" if n == 1 else "Delete Selection"
        msg = (
            "Delete this row? This cannot be undone except with Edit → Undo."
            if n == 1
            else f"Delete {n:,} selected rows? This cannot be undone except with Edit → Undo."
        )
        reply = QMessageBox.question(
            self,
            title,
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if n >= load_config().table_delete_batch_min:
            self._start_chunked_delete_prepare(oids)
            return
        cmd = UndoDeleteRowsCommand(self, oids=oids)
        if cmd.snapshot_count() == 0:
            QMessageBox.information(self, "Delete Selection", "No valid rows to delete.")
            return
        self._undo_stack.push(cmd)

    def _start_chunked_delete_prepare(self, oids: frozenset[int]) -> None:
        """Build undo snapshots in chunks so the UI stays responsive before delete runs."""
        self._cancel_chunked_table_delete()
        self._table_delete_job_gen = int(getattr(self, "_table_delete_job_gen", 0)) + 1
        gen = self._table_delete_job_gen
        total = len(oids)
        light = total >= load_config().table_delete_batch_min
        self._table_delete_ctx = {
            "gen": gen,
            "oids": frozenset(int(x) for x in oids),
            "light": light,
            "snapshots": [],
            "row_idx": 0,
            "total_rows": self._table_model.rowCount(),
        }
        self._set_selection_status(f"Preparing delete… (0/{total:,} rows)", pump=True)
        QTimer.singleShot(0, self._table_delete_prepare_step)

    def _table_delete_prepare_step(self) -> None:
        ctx = getattr(self, "_table_delete_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_table_delete_job_gen", -1):
            return
        kill: frozenset[int] = ctx["oids"]
        light = bool(ctx["light"])
        data_headers = [h for h in self.headers[2:] if h != "Structure"]
        model = self._table_model
        rows = model._rows  # noqa: SLF001
        total_rows = len(rows)
        total_delete = len(kill)
        idx = int(ctx["row_idx"])
        chunk = max(2000, load_config().table_delete_chunk_rows)
        end = min(idx + chunk, total_rows)
        snapshots: list[DeleteRowSnapshot] = ctx["snapshots"]
        found_before = len(snapshots)
        for j in range(idx, end):
            row = rows[j]
            oid = int(row.oid)
            if oid not in kill:
                continue
            cells = {h: str(row.values.get(h, "") or "") for h in data_headers}
            if light:
                snapshots.append(DeleteRowSnapshot(orig_row=j, oid=oid, cells=cells, light=True))
            else:
                pm = self.mols.get(oid)
                mol_copy = Chem.Mol(pm) if pm is not None else None
                png = model.structure_png_bytes(oid)
                spm = None if png else model.structure_pixmap_copy(oid)
                extra = model.extra_column_pixmaps_copy(oid) if total_delete <= 1 else {}
                snapshots.append(
                    DeleteRowSnapshot(
                        orig_row=j,
                        oid=oid,
                        cells=cells,
                        mol_copy=mol_copy,
                        structure_pixmap=spm,
                        structure_png=png,
                        extra_pixmaps=extra,
                        light=False,
                    )
                )
        ctx["row_idx"] = end
        found = len(snapshots) - found_before
        done_delete = len(snapshots)
        self._set_selection_status(
            f"Preparing delete… ({done_delete:,}/{total_delete:,} rows, scanned {end:,}/{total_rows:,})"
        )
        if end < total_rows:
            QTimer.singleShot(0, self._table_delete_prepare_step)
            return
        self._table_delete_ctx = None
        if not snapshots:
            QMessageBox.information(self, "Delete Selection", "No valid rows to delete.")
            self._set_selection_status("Delete cancelled — no matching rows.", pump=True)
            return
        if found < total_delete:
            # Rows may have been removed while preparing; keep only snapshots we collected.
            pass
        cmd = UndoDeleteRowsCommand(self, snapshots=snapshots)
        self._undo_stack.push(cmd)

    def edit_delete_selection(self) -> None:
        """Delete selected rows, columns, or cell values depending on what is selected."""
        kind = self._delete_selection_kind()
        if kind == "empty":
            QMessageBox.information(self, "Delete Selection", "Nothing selected.")
            return
        if kind == "both":
            oids = self._selected_oids_for_delete()
            cols = self._selected_full_column_indices()
            names = [
                self.headers[c]
                for c in cols
                if 0 <= c < len(self.headers) and self.headers[c] not in ("ID_HIDDEN", "Structure")
            ]
            if not oids:
                self._confirm_and_push_delete_columns(cols)
                return
            if not names:
                self._confirm_and_push_delete_rows(oids=oids)
                return
            choice = self._ask_delete_rows_or_columns(len(oids), names)
            if choice == "rows":
                self._confirm_and_push_delete_rows(oids=oids)
            elif choice == "columns":
                self._confirm_and_push_delete_columns(cols)
            return
        if kind == "columns":
            self._confirm_and_push_delete_columns(self._selected_full_column_indices())
            return
        if kind == "cells":
            self._confirm_and_push_clear_cells()
            return
        self._confirm_and_push_delete_rows(oids=self._selected_oids_for_delete())

    def _apply_pasted_cell_value(self, row: int, col: int, oid: int, text: str) -> bool:
        """Write one pasted value without refreshing bounds or filters."""
        if not text and col == CompoundTableModel.STRUCTURE_COL:
            return False
        if col == CompoundTableModel.STRUCTURE_COL:
            mol = self._mol_from_structure_text(text)
            if mol is None:
                return False
            self.mols[oid] = mol
            if "SMILES" in self.headers:
                try:
                    self._table_model.set_cell_text(oid, "SMILES", mol_to_canonical_smiles(mol))
                except Exception:
                    pass
            self._table_model.set_structure_pixmap(oid, None)
            self._clear_cell_depiction(col, oid)
            return True
        h = self.headers[col] if 0 <= col < len(self.headers) else ""
        if h and self._table_model.is_pixmap_data_column(h):
            mol = self._mol_from_structure_text(text)
            if mol is None:
                return False
            try:
                smi = mol_to_canonical_smiles(mol)
            except Exception:
                smi = text
            self._table_model.set_backing_text(oid, h, smi)
            self._table_model.set_column_pixmap(oid, h, None)
            self._clear_cell_depiction(col, oid)
            return True
        if not self._table_model.column_accepts_text_edit(col):
            return False
        self._table_model.set_cell_text(oid, h, text)
        return True

    def _clear_cell_depiction(self, col: int, oid: int) -> None:
        """A replaced structure no longer matches coordinates stored for the old drawing."""
        column = depiction_column_for_cell(self, col)
        store = getattr(self, "_depiction_coords", None)
        if column and store is not None:
            store.discard_column_oids(column, [int(oid)])

    def _paste_clipboard_into_table_cell(
        self,
        row: int,
        col: int,
        oid: int | None,
        *,
        clip_text: str | None = None,
        quiet: bool = False,
    ) -> bool:
        if oid is None:
            return False
        if clip_text is not None:
            text = clip_text.strip()
        else:
            text = (QApplication.clipboard().text() or "").strip()
        if not text:
            if not quiet:
                QMessageBox.information(self, "Paste", "Clipboard is empty.")
            return False
        if col == CompoundTableModel.STRUCTURE_COL or (
            0 <= col < len(self.headers)
            and self._table_model.is_pixmap_data_column(self.headers[col])
        ):
            if self._mol_from_structure_text(text) is None:
                if not quiet:
                    QMessageBox.warning(
                        self,
                        "Paste",
                        "Could not interpret the clipboard as a structure (try SMILES, InChI, or a MolBlock).",
                    )
                return False
        if not self._apply_pasted_cell_value(row, col, oid, text):
            return False
        self.calculate_global_bounds()
        self.apply_filters()
        if not quiet:
            if col == CompoundTableModel.STRUCTURE_COL or (
                0 <= col < len(self.headers)
                and self._table_model.is_pixmap_data_column(self.headers[col])
            ):
                self.status_label.setText("Structure updated from clipboard.")
            else:
                self.status_label.setText("Cell updated from clipboard.")
        return True
