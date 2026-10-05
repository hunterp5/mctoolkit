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

"""Table chrome file-split for ``ChemistryWorkspaceWindow`` (edit/menu/search/filters)."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
)

from ...conformers.conformer_column_codec import (
    demote_v1_cell_to_sidecar,
    is_packed_ensemble_header,
    rehydrate_v1_confs_cell,
)
from ...platform_support.exception_policy import log_swallowed_exception
from ...services.table_selection import (
    collect_canonical_keys_from_column,
)
from ...chem.molecule_conversion import (
    canonical_structure_key_from_smiles as canonical_structure_key_from_smiles_fn,
    mol_to_canonical_smiles,
)
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

from ..filters import FilterPanelMixin
from .table_edit_mixin import TableEditMixin
from .table_menu_mixin import TableMenuMixin
from .table_search_mixin import TableSearchMixin

logger = logging.getLogger(__name__)


class TableUIMixin(
    TableEditMixin,
    TableMenuMixin,
    TableSearchMixin,
    FilterPanelMixin,
):
    def _open_column_color_dialog(self, col: int) -> None:
        if col < 2 or col >= len(self.headers):
            return
        header_name = self.headers[col]
        if self._table_model.is_pixmap_data_column(header_name):
            return
        from ..dialogs.column_color import ColumnColorDialog

        bounds = self._table_model.numeric_bounds_by_column().get(header_name, {})
        dlg = ColumnColorDialog(
            self,
            header_name=header_name,
            numeric_bounds=bounds,
            current_mode=self._table_model.column_color_mode(header_name),
            current_spec=self._table_model.column_color_rule_spec(header_name),
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        cfg = dlg.result_config()
        mode = cfg.get("mode", "off")
        if mode == "numeric":
            self._table_model.set_column_color_numeric_gradient(
                header_name,
                min_value=float(cfg.get("min", 0.0)),
                max_value=float(cfg.get("max", 1.0)),
                low_color=cfg["low_color"],
                high_color=cfg["high_color"],
                alpha=int(cfg.get("alpha", 96)),
            )
            self.status_label.setText(f"Coloring applied: {header_name} (numeric gradient).")
            return
        if mode == "categorical":
            self._table_model.set_column_color_categorical(
                header_name,
                alpha=int(cfg.get("alpha", 88)),
            )
            self.status_label.setText(f"Coloring applied: {header_name} (categorical).")
            return
        if mode == "numeric3":
            self._table_model.set_column_color_three_point_gradient(
                header_name,
                min_value=float(cfg.get("min", 0.0)),
                mid_value=float(cfg.get("mid", 0.5)),
                max_value=float(cfg.get("max", 1.0)),
                low_color=cfg["low_color"],
                mid_color=cfg["mid_color"],
                high_color=cfg["high_color"],
                alpha=int(cfg.get("alpha", 96)),
            )
            self.status_label.setText(f"Coloring applied: {header_name} (3-color gradient).")
            return
        self._table_model.clear_column_coloring(header_name)
        self.status_label.setText(f"Coloring cleared: {header_name}.")

    def _apply_table_sort(self, logical_col: int, ascending: bool, sort_kind: str) -> None:
        """Apply sort on the model and record state for session save/restore."""
        order = Qt.AscendingOrder if ascending else Qt.DescendingOrder
        self.table.setSortingEnabled(False)
        self._table_model.sort(logical_col, order, sort_kind=sort_kind)
        self._session_sort = {"column": logical_col, "ascending": ascending, "mode": sort_kind}
        header = self.headers[logical_col] if 0 <= int(logical_col) < len(self.headers) else ""
        kind = "numeric" if str(sort_kind) == "numeric" else "alphabetic"
        direction = "ascending" if ascending else "descending"
        name = f" '{header}'" if header else ""
        self.status_label.setText(f"Sorted{name} {kind} {direction}.")

    def _on_horizontal_header_section_clicked(self, logical_index: int) -> None:
        if logical_index < 0 or logical_index >= len(self.headers):
            return
        if self.headers[logical_index] == "ID_HIDDEN":
            return
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier:
            anchor = getattr(self, "_column_selection_anchor", None)
            if anchor is None or anchor < 0 or anchor >= len(self.headers):
                self._column_selection_anchor = logical_index
                self._select_columns([logical_index], anchor_col=logical_index)
            else:
                self._select_column_range(anchor, logical_index)
            return
        self._column_selection_anchor = logical_index
        self._select_columns([logical_index], anchor_col=logical_index)

    def _row_cells_dict(self, row: int) -> dict[str, str]:
        out: dict[str, str] = {}
        for name in self.headers[2:]:
            c = self.headers.index(name)
            out[name] = self._table_cell_text(row, c)
        return out

    def _on_column_moved(self, logicalIndex: int, oldVisualIndex: int, newVisualIndex: int) -> None:
        # Keep `ID_HIDDEN` (col 0) and `Structure` (col 1) fixed at visual positions 0 and 1.
        # Qt will still allow drops around them; we snap them back after the move.
        h = self.table.horizontalHeader()
        if self._table_model.columnCount() < 2:
            return
        if h.visualIndex(0) != 0:
            h.moveSection(h.visualIndex(0), 0)
        if h.visualIndex(1) != 1:
            h.moveSection(h.visualIndex(1), 1)

    def _visual_logical_columns(self) -> list[int]:
        """Logical column indices sorted by current visual order."""
        h = self.table.horizontalHeader()
        n = self._table_model.columnCount()
        cols = list(range(n))
        cols.sort(key=h.visualIndex)
        return cols

    def _table_cell_text(self, row: int, col: int) -> str:
        """Best-effort text for exporting (structure column has no text when shown as pixmap)."""
        if col == 1:
            return ""
        return (self._table_model.cell_text(row, col) or "").strip()

    def _selected_smiles_strings(self) -> list[str]:
        """SMILES for PubChem/ChEMBL: canonical SMILES from any resolvable chemistry in each selected row."""
        if not self.headers:
            return []
        items = self.table.selectionModel().selectedIndexes()
        if not items:
            return []
        rows = sorted({i.row() for i in items})
        out: list[str] = []
        seen: set[str] = set()
        for r in rows:
            mol = self._mol_for_structure_row(r)
            if mol is None:
                continue
            try:
                smi = mol_to_canonical_smiles(mol).strip()
            except Exception:
                smi = ""
            if smi and smi not in seen:
                out.append(smi)
                seen.add(smi)
        return out

    def canonical_structure_key_from_smiles(self, smiles: str) -> str | None:
        """Canonical isomeric SMILES key for duplicate detection; ``None`` if not parseable."""
        return canonical_structure_key_from_smiles_fn(smiles)

    def existing_canonical_structure_keys(self) -> set[str]:
        """Canonical SMILES keys already present in the primary SMILES column (for de-duplication)."""
        h = self._canonical_smiles_header_for_updates()
        if not h or h not in self.headers:
            return set()
        ci = self.headers.index(h)
        return collect_canonical_keys_from_column(
            self._table_model.rowCount(),
            cell_text=lambda r: self._table_model.cell_text(r, ci),
            key_fn=self.canonical_structure_key_from_smiles,
        )

    def clear_all(self):
        from ...storage import reset_confs_sidecar, reset_mol_store

        keep_loading = bool(getattr(self, "_ingest_loading", False))
        reset_confs_sidecar(self)
        reset_mol_store(self)
        self._som_browse_records = []
        clearer = getattr(self, "_store_last_dock_results", None)
        if callable(clearer):
            clearer([], title="Pose browser")
        else:
            self._last_dock_results = None
        self._dock_pose_zoomed = False
        if getattr(self, "_undo_stack", None) is not None:
            self._undo_stack.clear()
        try:
            from ...chem.fingerprint_cache import clear as clear_fingerprint_cache

            clear_fingerprint_cache()
        except Exception:
            log_swallowed_exception(logger, "fingerprint_cache.clear failed during clear_all")
        try:
            from ...ionization.microstate_cache import clear as clear_microstate_cache

            clear_microstate_cache()
        except Exception:
            log_swallowed_exception(logger, "microstate_cache.clear failed during clear_all")
        self._table_model.clear()
        discard_plots = getattr(self, "_discard_docked_plot_widgets", None)
        if callable(discard_plots):
            discard_plots()
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is not None:
            from .workspace_layout import LAYOUT_TABLE_ONLY

            mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=False)
        if not keep_loading:
            show_idle = getattr(self, "_show_idle_workspace", None)
            if callable(show_idle):
                show_idle()
            else:
                set_stack = getattr(self, "_set_workspace_stack_index", None)
                if callable(set_stack):
                    set_stack(0)
                elif getattr(self, "_table_stack", None) is not None:
                    self._table_stack.setCurrentIndex(0)
        self.zoomed_ids = set()
        for f in self.filters:
            f.deleteLater()
        self.filters, self.headers, self.global_bounds = [], [], {}
        self._logarithmic_columns = set()
        self.next_oid = 0
        self._structure_field_override = None
        self._export_prep = None
        self._export_busy = False
        self._render2d_queue = None
        self._pending_session_table_layout = None
        self._pending_session_workspace_layout = None
        self._pending_session_column_order = None
        self._session_awaiting_ready = False
        self._session_waiting_for_render = False
        self._ingest_waiting_for_render = False
        self._session_hold_workspace_surfaces = False
        self._session_plot_wait_deadline = None
        self._session_search_want_visible = False
        self._session_search_rerun = False
        reset_search = getattr(self, "_reset_table_search_panel", None)
        if callable(reset_search):
            reset_search()
        if not keep_loading:
            # Floating hosts from a prior session; do not reveal the empty table page.
            show_ws = getattr(self, "_show_session_workspace_when_ready", None)
            if callable(show_ws):
                show_ws()
            show_idle = getattr(self, "_show_idle_workspace", None)
            if callable(show_idle):
                show_idle()
        self._restore_render2d_batch_environment()
        self._session_restore_ctx = None
        abort_csv = getattr(self, "_abort_csv_session_load", None)
        if callable(abort_csv):
            abort_csv()
        else:
            self._csv_session_ctx = None
        self._session_load_generation = int(getattr(self, "_session_load_generation", 0)) + 1
        self._invalidate_substructure_async_jobs()
        self._sqlite_rebuild_gen = int(getattr(self, "_sqlite_rebuild_gen", 0)) + 1
        self._sqlite_rebuild_pending_filters = False
        self._pending_batches = []
        self._processing_batches = False
        self._last_batch_received = False
        if not keep_loading:
            self._set_ingest_loading(False)
        self._ingest_sqlite_bulk_active = False
        self._ingest_sqlite_paused_dirty = False
        self._ingest_sqlite_bulk_headers = None
        if getattr(self, "_sqlite_store", None) is not None:
            try:
                self._sqlite_rebuild_in_progress = True
                self._sqlite_store.rebuild(["ID_HIDDEN", "Structure"], [])
                self._sqlite_store_dirty = False
            except Exception:
                log_swallowed_exception(logger, "sqlite_store.rebuild failed during clear_all")
            finally:
                self._sqlite_rebuild_in_progress = False
        self._structures_queued = 0
        self._import_progress_active = False
        self._import_render_done = 0
        self._import_render_goal = 0
        self._import_building_progress_shown = False
        self._clear_tool_progress()
        self._session_sort = None
        self._selected_oids_override = None

    def _migrate_legacy_confs_cells_to_sidecar(self) -> None:
        """Move embedded v1 conformer payloads out of ``confs`` / ``superpose`` cells into ``_confs_blocks_sidecar``."""
        from ...storage import ensure_confs_sidecar

        sc = ensure_confs_sidecar(self)
        cols = [c for c in self.headers if is_packed_ensemble_header(c)]
        if not cols:
            return
        n = self._table_model.rowCount()
        for r in range(n):
            t0 = self._table_model.cell_text(r, 0)
            if not t0.isdigit():
                continue
            oid = int(t0)
            for col in cols:
                raw = self._table_model.backing_value_for_row_header(r, col)
                light, b64 = demote_v1_cell_to_sidecar(raw, col)
                if b64 is not None:
                    sc[(oid, col)] = b64
                    if light != raw:
                        self._table_model.set_cell_text(oid, col, light)

    def _confs_sidecar_discard_oids(self, oids: list[int]) -> None:
        from ...storage import EnsembleStore

        sc = getattr(self, "_confs_blocks_sidecar", None)
        if sc is None or not oids:
            return
        if isinstance(sc, EnsembleStore):
            sc.discard_oids(oids)
            return
        dead = {int(o) for o in oids}
        for k in list(sc.keys()):
            if k[0] in dead:
                del sc[k]

    def _confs_sidecar_copy_for_new_row(self, src_oid: int, dst_oid: int) -> None:
        from ...storage import EnsembleStore

        sc = getattr(self, "_confs_blocks_sidecar", None)
        if sc is None:
            return
        cols = [h for h in self.headers if is_packed_ensemble_header(h)]
        if isinstance(sc, EnsembleStore):
            sc.copy_oid(src_oid, dst_oid, cols)
            return
        for col in cols:
            b = sc.get((int(src_oid), col))
            if b:
                sc[(int(dst_oid), col)] = b

    def _export_cell_text(self, row: int, col: int) -> str:
        """Cell text for export: rehydrate ``confs`` / ``superpose`` so files stay self-contained."""
        if col == 1:
            return ""
        h = self.headers[col] if 0 <= col < len(self.headers) else ""
        if is_packed_ensemble_header(h):
            raw = self._table_model.backing_value_for_row_header(row, h)
            t0 = self._table_model.cell_text(row, 0)
            oid = int(t0) if t0.isdigit() else -1
            if oid >= 0:
                sc = getattr(self, "_confs_blocks_sidecar", None)
                if sc is None:
                    sc = {}
                return rehydrate_v1_confs_cell(raw, h, oid, sc)
        return (self._table_cell_text(row, col) or "").strip()

    def _on_selection_browser_dialog_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        try:
            sender = self.sender()
        except RuntimeError:
            return
        current = getattr(self, "_selection_browser_dialog", None)
        if sender is not None and current is not None and current is not sender:
            return
        self._selection_browser_dialog = None

    def open_selection_browser(
        self,
        *,
        focus_oid: int | None = None,
        preview_mode: str | None = None,
    ) -> None:
        """Open modeless dialog to walk selected rows with structure preview."""
        from ..selection_browser import SelectionBrowserDialog, SelectionBrowserWidget

        def _apply(panel) -> None:
            if panel is None:
                return
            apply_fn = getattr(panel, "apply_open_request", None)
            if callable(apply_fn):
                apply_fn(focus_oid=focus_oid, preview_mode=preview_mode)
            else:
                panel.refresh_from_app(preserve_position=True)

        for w in self.iter_docked_plot_widgets():
            if isinstance(w, SelectionBrowserWidget):
                mgr = self._workspace()
                if mgr is not None:
                    pane = mgr.pane_for_widget(w)
                    if pane is not None:
                        mgr.set_preferred_pane(pane)
                self.show_docked_plot_panel()
                _apply(w)
                w.raise_()
                self.status_label.setText("Browser: focused in workspace pane.")
                return

        def _factory():
            return SelectionBrowserDialog(self)

        dlg = reuse_or_show_modeless_singleton(
            self,
            "_selection_browser_dialog",
            _factory,
            on_reused_visible=lambda d: _apply(getattr(d, "_panel", None)),
        )
        _apply(getattr(dlg, "_panel", None))
