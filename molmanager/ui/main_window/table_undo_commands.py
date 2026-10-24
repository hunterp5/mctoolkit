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

"""QUndoCommand implementations for table row/column/cell edits."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QUndoCommand
from rdkit import Chem

from ...platform_support.config import load_config
from ...table.structure_depiction_layout import structure_column_minimum_width
from ...chem.molecule_conversion import mol_to_canonical_smiles
from ..compound_table_model import CompoundTableModel
from ..widgets import CategoryFilterCard, FilterCard, TextFilterCard

if TYPE_CHECKING:
    from ..app_kernel import AppKernel


def depiction_column_for_cell(app, col: int) -> str | None:
    """Column name whose stored orientation this cell draws, if any."""
    if col == CompoundTableModel.STRUCTURE_COL:
        return "Structure"
    headers = getattr(app, "headers", None) or []
    if not 0 <= col < len(headers):
        return None
    header = headers[col]
    model = getattr(app, "_table_model", None)
    if model is not None and model.is_pixmap_data_column(header):
        return header
    return None


def capture_depiction_blob(app, column: str | None, oid: int) -> bytes | None:
    """Packed coordinates for one cell, or ``None`` when the cell has no pose."""
    store = getattr(app, "_depiction_coords", None)
    if store is None or not column:
        return None
    return store.get(str(column), int(oid))


def restore_depiction_blob(app, column: str | None, oid: int, blob: bytes | None) -> None:
    """Put *blob* back, or drop the cell's pose when *blob* is empty."""
    store = getattr(app, "_depiction_coords", None)
    if store is None or not column:
        return
    if blob:
        store.set(str(column), int(oid), bytes(blob))
    else:
        store.discard_column_oids(str(column), [int(oid)])


__all__ = [
    "UndoDeleteRowsCommand",
    "UndoPasteCellCommand",
    "UndoUpdateRowStructureCommand",
    "UndoPasteBlockCommand",
    "UndoCellTextChangeCommand",
    "UndoClearCellsCommand",
    "UndoDeleteColumnCommand",
    "UndoDuplicateColumnCommand",
    "UndoInsertRowCommand",
    "UndoAddBlankRowCommand",
    "UndoAddBlankColumnCommand",
    "UndoLogarithmicColumnCommand",
    "UndoPrecisionColumnCommand",
    "collect_delete_row_snapshots",
]


@dataclass
class DeleteRowSnapshot:
    """Captured row state for undo after delete."""

    orig_row: int
    oid: int
    cells: dict[str, str]
    mol_copy: Chem.Mol | None = None
    structure_pixmap: QPixmap | None = None
    structure_png: bytes | None = None
    extra_pixmaps: dict[str, QPixmap] = field(default_factory=dict)
    light: bool = False


def collect_delete_row_snapshots(
    app: AppKernel,
    oids: frozenset[int],
    *,
    light: bool,
) -> list[DeleteRowSnapshot]:
    """One table scan — avoids per-OID ``logical_row_for_oid`` when deleting large selections."""
    if not oids:
        return []
    kill = {int(x) for x in oids}
    data_headers = [h for h in app.headers[2:] if h != "Structure"]
    out: list[DeleteRowSnapshot] = []
    model = app._table_model
    _ = light
    for r, row in enumerate(model._rows):  # noqa: SLF001 — bulk path; model owns rows
        oid = int(row.oid)
        if oid not in kill:
            continue
        cells = {h: str(row.values.get(h, "") or "") for h in data_headers}
        out.append(DeleteRowSnapshot(orig_row=r, oid=oid, cells=cells, light=True))
    return out


class UndoDeleteRowsCommand(QUndoCommand):
    """Undo/redo for removing one or more table rows (model + mols + structure pixmaps)."""

    def __init__(
        self,
        app: AppKernel,
        rows: list[int] | None = None,
        *,
        oids: frozenset[int] | None = None,
        snapshots: list[DeleteRowSnapshot] | None = None,
    ) -> None:
        if snapshots is not None:
            self._snapshots = list(snapshots)
        elif oids is not None:
            light = len(oids) >= load_config().table_delete_batch_min
            self._snapshots = collect_delete_row_snapshots(app, oids, light=light)
        else:
            oid_set = app._oids_for_row_indices(rows or [])
            light = len(oid_set) >= load_config().table_delete_batch_min
            self._snapshots = collect_delete_row_snapshots(app, oid_set, light=light)
        n = len(self._snapshots)
        super().__init__(f"Delete {n} row(s)" if n != 1 else "Delete row")
        self._app = app

    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def _use_batch_path(self) -> bool:
        return len(self._snapshots) >= load_config().table_delete_batch_min

    def _oids_from_snapshots(self) -> frozenset[int]:
        return frozenset(s.oid for s in self._snapshots)

    def _apply_delete_to_app(self) -> None:
        app = self._app
        oids = self._oids_from_snapshots()
        if self._use_batch_path():
            app._table_model.remove_rows_by_oids(oids)
        else:
            for oid in sorted(oids, key=lambda o: -app._table_model.logical_row_for_oid(o)):
                r = app._table_model.logical_row_for_oid(oid)
                if r >= 0:
                    app._table_model.remove_row_at(r)
        for oid in oids:
            app.mols.pop(oid, None)
            app.zoomed_ids.discard(oid)
        app._confs_sidecar_discard_oids(list(oids))
        depiction = getattr(app, "_depiction_coords", None)
        if depiction is not None:
            depiction.discard_oids(oids)
        app._clear_table_selection_after_delete()

    def _restore_rows_to_app(self) -> None:
        app = self._app
        ordered = sorted(self._snapshots, key=lambda s: s.orig_row)
        if self._use_batch_path():
            batch = [(s.orig_row, s.oid, dict(s.cells)) for s in ordered]
            app._table_model.insert_rows_batch(batch)
            for snap in ordered:
                self._restore_row_assets(app, snap, render_structure=False)
        else:
            for k, snap in enumerate(ordered):
                insert_at = snap.orig_row + k
                app._table_model.insert_row_at(insert_at, snap.oid, dict(snap.cells))
                self._restore_row_assets(app, snap, render_structure=True)

    @staticmethod
    def _restore_row_assets(
        app: AppKernel, snap: DeleteRowSnapshot, *, render_structure: bool = False
    ) -> None:
        smi = str(snap.cells.get("SMILES") or "").strip()
        mol = None
        if smi:
            try:
                mol = Chem.MolFromSmiles(smi)
            except Exception:
                mol = None
        if mol is None and snap.mol_copy is not None:
            mol = Chem.Mol(snap.mol_copy)
        if mol is not None:
            app.mols[snap.oid] = mol
            if snap.light and render_structure:
                render = getattr(app, "start_render_worker", None)
                if callable(render):
                    render(snap.oid, mol)
        else:
            app.mols.pop(snap.oid, None)
        if snap.structure_png:
            app._table_model.set_structure_png_bytes(snap.oid, snap.structure_png)
        elif snap.structure_pixmap is not None:
            app._table_model.set_structure_pixmap(snap.oid, snap.structure_pixmap)
        elif not snap.light:
            app._table_model.set_structure_pixmap(snap.oid, None)
        for h, pm in snap.extra_pixmaps.items():
            app._table_model.set_column_pixmap(snap.oid, h, pm)

    def _refresh_after_table_mutation(self) -> None:
        app = self._app
        mark = getattr(app, "_mark_sqlite_store_dirty", None)
        if callable(mark):
            mark()
        if self._use_batch_path():
            QTimer.singleShot(0, app._refresh_table_after_bulk_delete)
        else:
            app.calculate_global_bounds()
            app.apply_filters()

    def redo(self) -> None:
        app = self._app
        app.table.setSortingEnabled(False)
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            self._apply_delete_to_app()
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        self._refresh_after_table_mutation()
        app.table.setSortingEnabled(False)
        app.status_label.setText(f"Deleted {len(self._snapshots)} row(s).")

    def undo(self) -> None:
        app = self._app
        app.table.setSortingEnabled(False)
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            self._restore_rows_to_app()
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        self._refresh_after_table_mutation()
        app.table.setSortingEnabled(False)
        app.status_label.setText(f"Undo: restored {len(self._snapshots)} row(s).")


class UndoUpdateRowStructureCommand(QUndoCommand):
    """Replace one row's stored molecule with a structure from the sketcher."""

    def __init__(
        self, app: AppKernel, oid: int, mol: Chem.Mol, description: str = "Update table entry"
    ) -> None:
        super().__init__(description)
        self._app = app
        self._oid = int(oid)
        self._new = Chem.Mol(mol)
        prev = app.mols.get(self._oid)
        self._prev = Chem.Mol(prev) if prev is not None else None
        self._prev_depiction = capture_depiction_blob(app, "Structure", self._oid)
        self._prev_pm = app._table_model.structure_pixmap_copy(self._oid)
        self._had_smiles = "SMILES" in app.headers
        row = app.logical_row_for_oid(self._oid)
        self._prev_smiles = ""
        if self._had_smiles and row >= 0:
            self._prev_smiles = app._table_model.value_for_header(row, "SMILES") or ""

    def _apply(
        self,
        mol: Chem.Mol | None,
        smiles: str,
        pixmap,
        *,
        render: bool,
        depiction: bytes | None,
    ) -> None:
        app = self._app
        oid = self._oid
        if app.logical_row_for_oid(oid) < 0:
            return
        if mol is None:
            app.mols.pop(oid, None)
        else:
            app.mols[oid] = Chem.Mol(mol)
        restore_depiction_blob(app, "Structure", oid, depiction)
        if self._had_smiles and "SMILES" in app.headers:
            app._table_model.set_cell_text(oid, "SMILES", smiles)
        app._table_model.set_structure_pixmap(oid, pixmap)
        if render and mol is not None and hasattr(app, "start_render_worker"):
            app.start_render_worker(oid, Chem.Mol(mol), skip_mol_props=True)
        for name in ("_mark_session_dirty", "_mark_sqlite_store_dirty"):
            mark = getattr(app, name, None)
            if callable(mark):
                mark()

    def redo(self) -> None:
        try:
            smiles = mol_to_canonical_smiles(self._new)
        except Exception:
            smiles = ""
        self._apply(self._new, smiles, None, render=True, depiction=None)
        self._app.status_label.setText("Updated the table entry from the sketcher.")

    def undo(self) -> None:
        self._apply(
            self._prev,
            self._prev_smiles,
            self._prev_pm,
            render=self._prev is not None,
            depiction=self._prev_depiction,
        )
        self._app.status_label.setText("Undo: table entry restored.")


class UndoPasteCellCommand(QUndoCommand):
    """Undo/redo for pasting into one table cell (text or structure column)."""

    def __init__(self, app: AppKernel, row: int, col: int, oid: int, clip_text: str) -> None:
        super().__init__("Paste")
        self._app = app
        self._row = row
        self._col = col
        self._oid = oid
        self._clip = clip_text
        self._depiction_column = depiction_column_for_cell(app, col)
        self._prev_depiction = capture_depiction_blob(app, self._depiction_column, oid)
        if col == CompoundTableModel.STRUCTURE_COL:
            pm = app.mols.get(oid)
            self._prev_mol = Chem.Mol(pm) if pm is not None else None
            self._prev_pm = app._table_model.structure_pixmap_copy(oid)
            if "SMILES" in app.headers:
                self._prev_smiles = app._table_model.value_for_header(row, "SMILES")
            else:
                self._prev_smiles = ""
            self._prev_text = ""
            self._pixmap_header = None
        else:
            h = app.headers[col]
            self._prev_text = app._table_model.backing_value_for_row_header(row, h)
            self._prev_mol = None
            self._pixmap_header = h if app._table_model.is_pixmap_data_column(h) else None
            self._prev_pm = (
                app._table_model.column_pixmap_copy(oid, h) if self._pixmap_header else None
            )
            self._prev_smiles = ""

    def redo(self) -> None:
        self._app._paste_clipboard_into_table_cell(
            self._row, self._col, self._oid, clip_text=self._clip, quiet=True
        )

    def undo(self) -> None:
        app = self._app
        oid = self._oid
        if self._col == CompoundTableModel.STRUCTURE_COL:
            if self._prev_mol is not None:
                app.mols[oid] = Chem.Mol(self._prev_mol)
            else:
                app.mols.pop(oid, None)
            if "SMILES" in app.headers:
                app._table_model.set_cell_text(oid, "SMILES", self._prev_smiles or "")
            app._table_model.set_structure_pixmap(oid, self._prev_pm)
        else:
            h = app.headers[self._col]
            if self._pixmap_header:
                app._table_model.set_backing_text(oid, h, self._prev_text)
                app._table_model.set_column_pixmap(oid, h, self._prev_pm)
            else:
                app._table_model.set_cell_text(oid, h, self._prev_text)
        restore_depiction_blob(app, self._depiction_column, oid, self._prev_depiction)
        app.calculate_global_bounds()
        app.apply_filters()
        app.status_label.setText("Undo: paste reverted.")


@dataclass
class _PasteBlockCell:
    row: int
    col: int
    oid: int
    new_text: str
    prev_text: str = ""
    prev_mol: Chem.Mol | None = None
    prev_pm: QPixmap | None = None
    prev_smiles: str = ""
    pixmap_header: str | None = None
    depiction_column: str | None = None
    prev_depiction: bytes | None = None


class UndoPasteBlockCommand(QUndoCommand):
    """Undo/redo for Excel-style paste into a block of cells."""

    def __init__(self, app: AppKernel, writes: list[tuple[int, int, int, str]]) -> None:
        n = len(writes)
        super().__init__(f"Paste {n} cells" if n != 1 else "Paste")
        self._app = app
        self._cells: list[_PasteBlockCell] = []
        for row, col, oid, text in writes:
            cell = _PasteBlockCell(row=row, col=col, oid=oid, new_text=text)
            if col == CompoundTableModel.STRUCTURE_COL:
                pm = app.mols.get(oid)
                cell.prev_mol = Chem.Mol(pm) if pm is not None else None
                cell.prev_pm = app._table_model.structure_pixmap_copy(oid)
                if "SMILES" in app.headers:
                    cell.prev_smiles = app._table_model.value_for_header(row, "SMILES")
            else:
                h = app.headers[col]
                cell.prev_text = app._table_model.backing_value_for_row_header(row, h)
                cell.pixmap_header = h if app._table_model.is_pixmap_data_column(h) else None
                if cell.pixmap_header:
                    cell.prev_pm = app._table_model.column_pixmap_copy(oid, h)
            cell.depiction_column = depiction_column_for_cell(app, col)
            cell.prev_depiction = capture_depiction_blob(app, cell.depiction_column, oid)
            self._cells.append(cell)

    def redo(self) -> None:
        app = self._app
        apply = getattr(app, "_apply_pasted_cell_value", None)
        if not callable(apply):
            return
        for cell in self._cells:
            apply(cell.row, cell.col, cell.oid, cell.new_text)
        app.calculate_global_bounds()
        app.apply_filters()
        n = len(self._cells)
        if n == 1:
            app.status_label.setText("Cell updated from clipboard.")
        else:
            app.status_label.setText(f"Paste: filled {n:,} cell(s).")

    def undo(self) -> None:
        app = self._app
        for cell in reversed(self._cells):
            oid = cell.oid
            if cell.col == CompoundTableModel.STRUCTURE_COL:
                if cell.prev_mol is not None:
                    app.mols[oid] = Chem.Mol(cell.prev_mol)
                else:
                    app.mols.pop(oid, None)
                if "SMILES" in app.headers:
                    app._table_model.set_cell_text(oid, "SMILES", cell.prev_smiles or "")
                app._table_model.set_structure_pixmap(oid, cell.prev_pm)
            else:
                h = app.headers[cell.col]
                if cell.pixmap_header:
                    app._table_model.set_backing_text(oid, h, cell.prev_text)
                    app._table_model.set_column_pixmap(oid, h, cell.prev_pm)
                else:
                    app._table_model.set_cell_text(oid, h, cell.prev_text)
            restore_depiction_blob(app, cell.depiction_column, oid, cell.prev_depiction)
        app.calculate_global_bounds()
        app.apply_filters()
        app.status_label.setText("Undo: paste reverted.")


class UndoCellTextChangeCommand(QUndoCommand):
    """Undo/redo for context-menu Edit Value or Clear Value on a text data cell."""

    def __init__(self, app: AppKernel, oid: int, header: str, old_text: str, new_text: str) -> None:
        label = "Clear cell" if new_text == "" else "Edit cell"
        super().__init__(label)
        self._app = app
        self._oid = oid
        self._header = header
        self._old = old_text
        self._new = new_text

    def redo(self) -> None:
        app = self._app
        app._table_model.set_cell_text(self._oid, self._header, self._new)
        app.calculate_global_bounds()
        app.apply_filters()

    def undo(self) -> None:
        app = self._app
        app._table_model.set_cell_text(self._oid, self._header, self._old)
        app.calculate_global_bounds()
        app.apply_filters()
        app.status_label.setText("Undo: cell value reverted.")


class UndoClearCellsCommand(QUndoCommand):
    """Undo/redo clearing many text cells in one Edit → Delete Selection action."""

    def __init__(self, app: AppKernel, changes: list[tuple[int, str, str]]) -> None:
        n = len(changes)
        super().__init__(f"Clear {n} cell(s)" if n != 1 else "Clear cell")
        self._app = app
        self._changes = [(int(oid), str(header), str(old)) for oid, header, old in changes]

    def redo(self) -> None:
        app = self._app
        for oid, header, _old in self._changes:
            app._table_model.set_cell_text(oid, header, "")
        app.calculate_global_bounds()
        app.apply_filters()
        n = len(self._changes)
        app.status_label.setText(f"Cleared {n:,} cell(s)." if n != 1 else "Cleared cell.")

    def undo(self) -> None:
        app = self._app
        for oid, header, old in self._changes:
            app._table_model.set_cell_text(oid, header, old)
        app.calculate_global_bounds()
        app.apply_filters()
        app.status_label.setText("Undo: cell values restored.")


def _sync_filters_after_column_removed(app: AppKernel, hdr: str) -> None:
    """Update filter UI after a column is removed (no full-table bounds/filter pass)."""
    app.global_bounds.pop(hdr, None)
    cols = app._filterable_data_column_names()
    to_rem = []
    for f in app.filters:
        if isinstance(f, FilterCard):
            if f.update_prop_list(list(app.global_bounds.keys()), hdr, None):
                to_rem.append(f)
        elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
            if f.update_prop_list(cols, hdr, None):
                to_rem.append(f)
    for f in to_rem:
        app.remove_filter(f)


def _sync_bounds_after_column_restored(app: AppKernel, hdr: str) -> None:
    """Rescan bounds for one restored column and refresh filter property lists."""
    meta = app._table_model.numeric_bounds_for_header(hdr)
    if meta is not None:
        app.global_bounds[hdr] = meta
    cols = app._filterable_data_column_names()
    for f in app.filters:
        if isinstance(f, FilterCard):
            f.update_prop_list(list(app.global_bounds.keys()))
        elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
            f.update_prop_list(cols)


class UndoDeleteColumnCommand(QUndoCommand):
    """Undo/redo deleting a data column (not ID or Structure)."""

    def __init__(self, app: AppKernel, col: int) -> None:
        hdr = app.headers[col]
        super().__init__(f"Delete column '{hdr}'")
        self._app = app
        self._hdr = hdr
        self._logical_col = col
        self._was_pixmap = app._table_model.is_pixmap_data_column(hdr)
        self._was_logarithmic = hdr in getattr(app, "_logarithmic_columns", set())
        self._text_by_oid: dict[int, str] = {}
        self._png_by_oid: dict[int, bytes] = {}
        self._ionization_cache: dict | None = None
        self._ensemble_blobs: dict[int, str] = {}
        if self._was_pixmap:
            self._png_by_oid = app._table_model.column_png_bytes_by_oid(hdr)
        else:
            self._text_by_oid = app._table_model.column_text_by_oid(hdr)

    def redo(self) -> None:
        app = self._app
        try:
            idx = app.headers.index(self._hdr)
        except ValueError:
            return
        app._session_sort = None
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            app._table_model.remove_column_at(idx)
            app.headers.pop(idx)
            getattr(app, "_logarithmic_columns", set()).discard(self._hdr)
            _sync_filters_after_column_removed(app, self._hdr)
            from ..column_result_cache import release_deleted_column_cache

            self._ionization_cache, self._ensemble_blobs = release_deleted_column_cache(
                app, self._hdr
            )
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        app.status_label.setText(f"Deleted column '{self._hdr}'.")

    def undo(self) -> None:
        app = self._app
        idx = min(self._logical_col, len(app.headers))
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            app.headers.insert(idx, self._hdr)
            app._table_model.insert_column_at(idx, self._hdr, copy_from_logical=None)
            if self._was_pixmap:
                app._table_model.register_pixmap_column(self._hdr)
                app._table_model.set_column_png_bytes_batch(
                    self._hdr, list(self._png_by_oid.items())
                )
            else:
                pairs = list(self._text_by_oid.items())
                if pairs:
                    app._table_model.set_column_text_by_oids(self._hdr, pairs)
            from ..column_result_cache import restore_deleted_column_cache

            restore_deleted_column_cache(
                app, self._hdr, self._ionization_cache, self._ensemble_blobs
            )
            if self._was_logarithmic:
                getattr(app, "_logarithmic_columns", set()).add(self._hdr)
            _sync_bounds_after_column_restored(app, self._hdr)
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        app.status_label.setText(f"Undo: restored column '{self._hdr}'.")


class UndoLogarithmicColumnCommand(QUndoCommand):
    """Undo/redo applying or reversing log10 on a text data column."""

    def __init__(
        self,
        app: AppKernel,
        header: str,
        *,
        to_log: bool,
        changed_by_oid: dict[int, str],
        previous_by_oid: dict[int, str],
    ) -> None:
        verb = "Logarithmic" if to_log else "Linear"
        super().__init__(f"{verb} column '{header}'")
        self._app = app
        self._hdr = header
        self._to_log = bool(to_log)
        self._changed = {int(k): str(v) for k, v in changed_by_oid.items()}
        self._previous = {int(k): str(v) for k, v in previous_by_oid.items()}

    def _apply(self, oid_values: dict[int, str], *, logged: bool) -> None:
        app = self._app
        if self._hdr not in app.headers:
            return
        pairs = list(oid_values.items())
        if pairs:
            app._table_model.set_column_text_by_oids(self._hdr, pairs)
        logs = getattr(app, "_logarithmic_columns", None)
        if logs is not None:
            if logged:
                logs.add(self._hdr)
            else:
                logs.discard(self._hdr)
        sync = getattr(app, "_sync_global_bounds_for_headers", None)
        if callable(sync):
            sync([self._hdr])
        else:
            app.calculate_global_bounds()
        mark = getattr(app, "_mark_sqlite_store_dirty", None)
        if callable(mark):
            mark()

    def redo(self) -> None:
        self._apply(self._changed, logged=self._to_log)
        verb = "log10" if self._to_log else "linear"
        self._app.status_label.setText(f"Column '{self._hdr}' converted to {verb}.")

    def undo(self) -> None:
        self._apply(self._previous, logged=not self._to_log)
        verb = "linear" if self._to_log else "log10"
        self._app.status_label.setText(f"Undo: column '{self._hdr}' restored to {verb}.")


class UndoPrecisionColumnCommand(QUndoCommand):
    """Undo/redo reformatting numeric cells in a column to a fixed decimal precision."""

    def __init__(
        self,
        app: AppKernel,
        header: str,
        *,
        decimals: int,
        changed_by_oid: dict[int, str],
        previous_by_oid: dict[int, str],
    ) -> None:
        super().__init__(f"Precision column '{header}' ({int(decimals)} dp)")
        self._app = app
        self._hdr = header
        self._decimals = int(decimals)
        self._changed = {int(k): str(v) for k, v in changed_by_oid.items()}
        self._previous = {int(k): str(v) for k, v in previous_by_oid.items()}

    def _apply(self, oid_values: dict[int, str]) -> None:
        app = self._app
        if self._hdr not in app.headers:
            return
        pairs = list(oid_values.items())
        if pairs:
            app._table_model.set_column_text_by_oids(self._hdr, pairs)
        sync = getattr(app, "_sync_global_bounds_for_headers", None)
        if callable(sync):
            sync([self._hdr])
        else:
            app.calculate_global_bounds()
        mark = getattr(app, "_mark_sqlite_store_dirty", None)
        if callable(mark):
            mark()

    def redo(self) -> None:
        self._apply(self._changed)
        self._app.status_label.setText(
            f"Column '{self._hdr}' set to {self._decimals} decimal place(s)."
        )

    def undo(self) -> None:
        self._apply(self._previous)
        self._app.status_label.setText(f"Undo: column '{self._hdr}' precision restored.")


def _match_duplicated_column_width(
    app: AppKernel, src_col: int, dest_col: int, src_name: str
) -> None:
    """Give the inserted copy the same section width as its source.

    Structure (and other 2D pixmap columns) otherwise keep Qt's default header
    size, which is narrower than the depiction and squashes the render.
    """
    try:
        table = app.table
        width = int(table.columnWidth(src_col))
    except RuntimeError:
        return
    if src_name == "Structure" or app._table_model.is_pixmap_data_column(src_name):
        width = max(width, int(structure_column_minimum_width()))
    if width <= 0:
        return
    try:
        table.setColumnWidth(dest_col, width)
    except RuntimeError:
        return


def _unique_copy_header(headers: list[str], src_name: str) -> str:
    """Next unused ``{src} (Copy)`` / ``{src} (Copy N)`` header."""
    base = f"{src_name} (Copy)"
    if base not in headers:
        return base
    n = 2
    while f"{src_name} (Copy {n})" in headers:
        n += 1
    return f"{src_name} (Copy {n})"


def _snapshot_structure_column(app: AppKernel) -> tuple[dict[int, str], dict[int, bytes]]:
    """Backing SMILES and structure PNG bytes for a Structure-column duplicate."""
    model = app._table_model
    smiles: dict[int, str] = {}
    pngs: dict[int, bytes] = {}
    oids: list[int] = []
    mols = getattr(app, "mols", None) or {}
    n = model.rowCount()
    for r in range(n):
        oid = int(model.row_oid(r))
        if oid < 0:
            continue
        mol = mols.get(oid)
        if mol is None:
            resolve = getattr(app, "_mol_for_structure_row", None)
            if callable(resolve):
                mol = resolve(r)
        if mol is not None:
            try:
                smiles[oid] = mol_to_canonical_smiles(mol) or ""
            except Exception:
                smiles[oid] = ""
        oids.append(oid)
    for oid, raw in model.snapshot_structure_pngs(oids).items():
        if raw:
            pngs[int(oid)] = raw
    return smiles, pngs


class UndoDuplicateColumnCommand(QUndoCommand):
    """Undo/redo duplicating a column (insert copy next to source)."""

    def __init__(self, app: AppKernel, src_col: int, src_name: str) -> None:
        super().__init__(f"Duplicate column '{src_name}'")
        self._app = app
        self._src_name = src_name
        self._dup_name = _unique_copy_header(list(app.headers), src_name)
        self._structure_smiles: dict[int, str] | None = None
        self._structure_pngs: dict[int, bytes] | None = None
        if src_name == "Structure":
            smiles, pngs = _snapshot_structure_column(app)
            self._structure_smiles = smiles
            self._structure_pngs = pngs

    def redo(self) -> None:
        app = self._app
        try:
            src = app.headers.index(self._src_name)
        except ValueError:
            return
        app.table.setSortingEnabled(False)
        dup_col = src + 1
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            if self._structure_smiles is not None:
                app._table_model.duplicate_column_at(
                    dup_col,
                    self._dup_name,
                    src,
                    value_by_oid=self._structure_smiles,
                    png_by_oid=self._structure_pngs or {},
                    as_pixmap=True,
                )
            else:
                app._table_model.duplicate_column_at(dup_col, self._dup_name, src)
            app.headers.insert(dup_col, self._dup_name)
            _match_duplicated_column_width(app, src, dup_col, self._src_name)
            app.calculate_global_bounds()
            mark = getattr(app, "_mark_sqlite_store_dirty", None)
            if callable(mark):
                mark()
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        app.table.setSortingEnabled(False)
        app.status_label.setText(f"Duplicated column '{self._src_name}'.")

    def undo(self) -> None:
        app = self._app
        try:
            idx = app.headers.index(self._dup_name)
        except ValueError:
            return
        app._session_sort = None
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            app._table_model.remove_column_at(idx)
            app.headers.pop(idx)
            _sync_filters_after_column_removed(app, self._dup_name)
            mark = getattr(app, "_mark_sqlite_store_dirty", None)
            if callable(mark):
                mark()
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        app.status_label.setText(f"Undo: removed duplicated column '{self._dup_name}'.")


class UndoInsertRowCommand(QUndoCommand):
    """Undo/redo inserting a duplicated row (same data as source row at action time)."""

    def __init__(self, app: AppKernel, src_row: int) -> None:
        super().__init__("Duplicate row")
        self._app = app
        self._src_oid = -1
        self._cells: dict[str, str] = {}
        self._mol_copy: Chem.Mol | None = None
        self._new_oid: int | None = None
        t0 = app._table_model.cell_text(src_row, 0)
        if not t0.isdigit():
            return
        self._src_oid = int(t0)
        self._cells = dict(app._row_cells_dict(src_row))
        pm = app.mols.get(self._src_oid)
        self._mol_copy = Chem.Mol(pm) if pm is not None else None

    def is_valid(self) -> bool:
        return self._src_oid >= 0

    def redo(self) -> None:
        if not self.is_valid():
            return
        app = self._app
        if self._new_oid is None:
            self._new_oid = app.next_oid
            app.next_oid += 1
        src_r = app._table_model.logical_row_for_oid(self._src_oid)
        if src_r < 0:
            return
        insert_at = src_r + 1
        app.table.setSortingEnabled(False)
        app._table_model.insert_row_at(insert_at, self._new_oid, dict(self._cells))
        if self._mol_copy is not None:
            app.mols[self._new_oid] = Chem.Mol(self._mol_copy)
            app.start_render_worker(self._new_oid, app.mols[self._new_oid])
        app._confs_sidecar_copy_for_new_row(self._src_oid, self._new_oid)
        app.calculate_global_bounds()
        app.apply_filters()
        app.table.setSortingEnabled(False)
        app.status_label.setText("Duplicated row.")

    def undo(self) -> None:
        if self._new_oid is None:
            return
        app = self._app
        app.table.setSortingEnabled(False)
        r = app._table_model.logical_row_for_oid(self._new_oid)
        if r >= 0:
            app._table_model.remove_row_at(r)
        app.mols.pop(self._new_oid, None)
        app.zoomed_ids.discard(self._new_oid)
        app._confs_sidecar_discard_oids([self._new_oid])
        app.calculate_global_bounds()
        app.apply_filters()
        app.table.setSortingEnabled(False)
        app.status_label.setText("Undo: removed duplicated row.")


class UndoAddBlankRowCommand(QUndoCommand):
    """Undo/redo appending one or more empty table rows."""

    def __init__(self, app: AppKernel, count: int = 1) -> None:
        n = max(1, int(count))
        super().__init__("Add row" if n == 1 else f"Add {n} rows")
        self._app = app
        self._count = n
        self._new_oids: list[int] = []

    def redo(self) -> None:
        app = self._app
        ensure = getattr(app, "_ensure_blank_table_headers", None)
        if callable(ensure):
            ensure()
        if not self._new_oids:
            start = app.next_oid
            self._new_oids = list(range(start, start + self._count))
            app.next_oid = start + self._count
        app.table.setSortingEnabled(False)
        app._table_model.append_rows_batch([(oid, {}) for oid in self._new_oids])
        app.calculate_global_bounds()
        app.apply_filters()
        app.table.setSortingEnabled(False)
        last = self._new_oids[-1]
        row = app._table_model.logical_row_for_oid(last)
        if row >= 0:
            app.select_table_rows([row])
        mark = getattr(app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        sqlite = getattr(app, "_mark_sqlite_store_dirty", None)
        if callable(sqlite):
            sqlite()
        n = len(self._new_oids)
        app.status_label.setText("Added row." if n == 1 else f"Added {n} rows.")

    def undo(self) -> None:
        if not self._new_oids:
            return
        app = self._app
        kill = frozenset(self._new_oids)
        app.table.setSortingEnabled(False)
        app._table_model.remove_rows_by_oids(kill)
        for oid in self._new_oids:
            app.mols.pop(oid, None)
            app.zoomed_ids.discard(oid)
        discard = getattr(app, "_confs_sidecar_discard_oids", None)
        if callable(discard):
            discard(list(self._new_oids))
        app.calculate_global_bounds()
        app.apply_filters()
        app.table.setSortingEnabled(False)
        mark = getattr(app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        sqlite = getattr(app, "_mark_sqlite_store_dirty", None)
        if callable(sqlite):
            sqlite()
        n = len(self._new_oids)
        app.status_label.setText(
            "Undo: removed added row." if n == 1 else f"Undo: removed {n} added rows."
        )


class UndoAddBlankColumnCommand(QUndoCommand):
    """Undo/redo inserting empty data columns at the right edge."""

    def __init__(self, app: AppKernel, headers: str | list[str]) -> None:
        names = [headers] if isinstance(headers, str) else [h for h in headers if h]
        label = names[0] if len(names) == 1 else f"{len(names)} columns"
        super().__init__(f"Add column '{label}'" if len(names) == 1 else f"Add {label}")
        self._app = app
        self._headers = names

    def redo(self) -> None:
        app = self._app
        ensure = getattr(app, "_ensure_blank_table_headers", None)
        if callable(ensure):
            ensure()
        to_add = [h for h in self._headers if h not in app.headers]
        if not to_add:
            return
        nc = app._table_model.columnCount()
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            app.headers.extend(to_add)
            app._table_model.insert_columns_at(nc, to_add, None)
            _sync_bounds_after_column_restored(app, to_add[0])
            mark = getattr(app, "_mark_sqlite_store_dirty", None)
            if callable(mark):
                mark()
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        session = getattr(app, "_mark_session_dirty", None)
        if callable(session):
            session()
        n = len(to_add)
        if n == 1:
            app.status_label.setText(f"Added column '{to_add[0]}'.")
        else:
            app.status_label.setText(f"Added {n} columns.")

    def undo(self) -> None:
        app = self._app
        app._session_sort = None
        try:
            app.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            for hdr in reversed(self._headers):
                try:
                    idx = app.headers.index(hdr)
                except ValueError:
                    continue
                app._table_model.remove_column_at(idx)
                app.headers.pop(idx)
                _sync_filters_after_column_removed(app, hdr)
            mark = getattr(app, "_mark_sqlite_store_dirty", None)
            if callable(mark):
                mark()
        finally:
            try:
                app.table.setUpdatesEnabled(True)
            except Exception:
                pass
        session = getattr(app, "_mark_session_dirty", None)
        if callable(session):
            session()
        n = len(self._headers)
        if n == 1:
            app.status_label.setText(f"Undo: removed column '{self._headers[0]}'.")
        else:
            app.status_label.setText(f"Undo: removed {n} columns.")
