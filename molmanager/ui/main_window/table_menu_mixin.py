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

"""Header and cell context menus for the main table."""

from __future__ import annotations

from PyQt5.QtWidgets import QApplication, QInputDialog, QMenu

from ...table.column_log_transform import (
    column_can_apply_log10,
    column_can_apply_precision,
    transform_column_values_log10,
    transform_column_values_precision,
)
from ...conformers.conformer_column_codec import (
    is_packed_ensemble_header,
    resolve_blocks_b64_for_viewer,
)
from ...docking.pose_file_io import is_poses_header
from ..compound_table_model import CompoundTableModel
from ..strings import TOOL_RENDER_2D
from ..structure_copy_menu import add_structure_copy_submenu
from ..widgets import CategoryFilterCard, FilterCard, TextFilterCard
from .table_undo_commands import (
    UndoCellTextChangeCommand,
    UndoDeleteColumnCommand,
    UndoDuplicateColumnCommand,
    UndoInsertRowCommand,
    UndoLogarithmicColumnCommand,
    UndoPrecisionColumnCommand,
    depiction_column_for_cell,
)


class TableMenuMixin:
    """Column-header, row-header, and cell context menus."""

    def _add_structure_copy_submenu(self, menu: QMenu, mol) -> dict:
        """Copy submenu with SMILES and other structure formats. Maps actions to (text, status)."""
        return add_structure_copy_submenu(menu, mol)

    def _create_header_context_menu(self, col: int):
        """Column-header context menu. Dock results windows keep Sort and Select only."""
        if col < 0 or col >= len(self.headers):
            return None
        if self.headers[col] == "ID_HIDDEN":
            return None
        old_n = self.headers[col]
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        select_sub = menu.addMenu("Select")
        select_sub.setToolTipsVisible(True)
        select_all_act = select_sub.addAction("Select All")
        select_all_act.setObjectName("header_select_all")
        select_all_act.setToolTip(
            "Select every row currently visible in the table (respects active filters)."
        )
        select_sub.addSeparator()
        if self.headers[col] == "Structure":
            first_occ_act = select_sub.addAction("First Occurrence (per distinct structure)")
            first_occ_act.setToolTip(
                "For each distinct structure (canonical SMILES), select the first visible row where it appears."
            )
        else:
            first_occ_act = select_sub.addAction("First Occurrence (per distinct value)")
            first_occ_act.setToolTip(
                "For each non-empty cell text, select the first visible row where that value appears (top to bottom)."
            )
        first_occ_act.setObjectName("header_select_first_occurrence")
        empty_act = select_sub.addAction("Empty cells")
        empty_act.setObjectName("header_select_empty")
        if self.headers[col] == "Structure":
            empty_act.setToolTip(
                "Select visible rows with no chemical structure (no molecule in memory and no parseable SMILES or structure text)."
            )
        else:
            empty_act.setToolTip(
                "Select every visible row where this column is blank or whitespace-only."
            )
        if self._table_model.rowCount() > 0 and self.headers[col] != "Structure":
            sort_top = menu.addMenu("Sort")
            num_m = sort_top.addMenu("Numeric")
            sort_num_asc = num_m.addAction("Ascending")
            sort_num_asc.setObjectName("header_sort_num_asc")
            sort_num_desc = num_m.addAction("Descending")
            sort_num_desc.setObjectName("header_sort_num_desc")
            alp_m = sort_top.addMenu("Alphabetic")
            sort_alpha_asc = alp_m.addAction("Ascending")
            sort_alpha_asc.setObjectName("header_sort_alpha_asc")
            sort_alpha_desc = alp_m.addAction("Descending")
            sort_alpha_desc.setObjectName("header_sort_alpha_desc")
        if not getattr(self, "_dock_results_mode", False):
            menu.addSeparator()
            search_act = menu.addAction("Search")
            search_act.setObjectName("header_search")
            replace_act = menu.addAction("Find and Replace…")
            replace_act.setObjectName("header_find_replace")
            replace_act.setToolTip(
                "Find and replace text, wildcards, or comparisons. "
                "ID, Structure, and image columns cannot be edited."
            )
            if col >= 2 and not self._table_model.is_pixmap_data_column(old_n):
                color_act = menu.addAction("Color")
                color_act.setObjectName("header_color")
            from ...analysis.mmp_table import is_mmp_result_header

            if is_mmp_result_header(old_n):
                ledger_act = menu.addAction("Transform Ledger")
                ledger_act.setObjectName("header_mmp_transform_ledger")
                ledger_act.setToolTip(
                    "Open the MMP Transform Ledger for this session's MMP results."
                )
            menu.addSeparator()
            if old_n == "Structure":
                dup_act = menu.addAction(f"Duplicate '{old_n}'")
                dup_act.setObjectName("header_duplicate")
                dup_act.setToolTip(
                    "Copy structures into a new chemistry column (SMILES and 2D images). "
                    "The copy can be renamed, deleted, and used as a tool source like Protonated."
                )
            else:
                ren_act = menu.addAction(f"Rename '{old_n}'")
                ren_act.setObjectName("header_rename")
                dup_act = menu.addAction(f"Duplicate '{old_n}'")
                dup_act.setObjectName("header_duplicate")
                del_act = menu.addAction(f"Delete '{old_n}'")
                del_act.setObjectName("header_delete")
            menu.addSeparator()
            log_act = menu.addAction("Logarithmic")
            log_act.setObjectName("header_logarithmic")
            log_act.setCheckable(True)
            log_act.setChecked(old_n in getattr(self, "_logarithmic_columns", set()))
            log_act.setEnabled(self._column_can_toggle_logarithmic(old_n))
            log_act.setToolTip(
                "Convert positive numeric values to log10. Click again to convert back. "
                "Disabled when the column has no positive numeric values, or any numeric "
                "value ≤ 0 (while not already logarithmic)."
            )
            prec_act = menu.addAction("Precision…")
            prec_act.setObjectName("header_precision")
            prec_act.setEnabled(self._column_can_apply_precision(old_n))
            prec_act.setToolTip(
                "Round numeric values in this column to a chosen number of decimal places. "
                "Disabled when the column has no numeric values."
            )
        return menu

    def show_header_menu(self, pos):
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        menu = self._create_header_context_menu(col)
        if menu is None:
            return
        old_n = self.headers[col]
        action = menu.exec_(self.table.horizontalHeader().mapToGlobal(pos))
        if action is None:
            return
        name = action.objectName()
        if name == "header_sort_num_asc":
            self._apply_table_sort(col, True, "numeric")
        elif name == "header_sort_num_desc":
            self._apply_table_sort(col, False, "numeric")
        elif name == "header_sort_alpha_asc":
            self._apply_table_sort(col, True, "alphabetic")
        elif name == "header_sort_alpha_desc":
            self._apply_table_sort(col, False, "alphabetic")
        elif name == "header_search":
            self.open_table_search_with_column(col)
        elif name == "header_find_replace":
            self.open_find_replace_with_column(col)
        elif name == "header_color":
            self._open_column_color_dialog(col)
        elif name == "header_mmp_transform_ledger":
            opener = getattr(self, "open_mmp_transform_ledger_for_last_run", None)
            if callable(opener):
                opener()
        elif name == "header_logarithmic":
            self._toggle_column_logarithmic(old_n)
        elif name == "header_precision":
            self._apply_column_precision(old_n)
        elif name == "header_select_all":
            self._select_all_rows()
        elif name == "header_select_first_occurrence":
            if self.headers[col] == "Structure":
                self._select_first_occurrence_per_distinct_structure()
            else:
                self._select_first_occurrence_per_distinct_value(col)
        elif name == "header_select_empty":
            if self.headers[col] == "Structure":
                self._select_empty_structure_cells()
            else:
                self._select_empty_cells_in_column(col)
        elif name == "header_delete":
            self._undo_stack.push(UndoDeleteColumnCommand(self, col))
        elif name == "header_rename":
            name_in, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_n)
            if ok and name_in:
                self._rename_column_header(col, name_in)
        elif name == "header_duplicate":
            self._undo_stack.push(UndoDuplicateColumnCommand(self, col, old_n))

    def _rename_column_header(self, col: int, new_name: str) -> None:
        """Rename a data column header and update filters / bounds that reference it."""
        if col < 0 or col >= len(self.headers):
            return
        old_n = self.headers[col]
        name_in = str(new_name or "").strip()
        if not name_in:
            return
        self.headers[col] = name_in
        self._table_model.rename_header_at(col, name_in)
        logs = getattr(self, "_logarithmic_columns", None)
        if logs is not None and old_n in logs:
            logs.discard(old_n)
            logs.add(name_in)
        if old_n in self.global_bounds:
            self.global_bounds[name_in] = self.global_bounds.pop(old_n)
        contexts = getattr(self, "_pose_column_contexts", None)
        pose_column = is_poses_header(old_n) or (isinstance(contexts, dict) and old_n in contexts)
        if isinstance(contexts, dict) and old_n in contexts and old_n != name_in:
            contexts[name_in] = contexts.pop(old_n)
            if getattr(self, "_last_pose_column", None) == old_n:
                self._last_pose_column = name_in
            snap = getattr(self, "_last_dock_results", None)
            if isinstance(snap, dict) and snap.get("pose_column") == old_n:
                snap["pose_column"] = name_in
        if pose_column and old_n != name_in:
            self._retarget_packed_column_store(old_n, name_in)
        cols = self._filterable_data_column_names()
        for f in self.filters:
            if isinstance(f, FilterCard):
                f.update_prop_list(list(self.global_bounds.keys()), old_n, name_in)
            elif isinstance(f, (TextFilterCard, CategoryFilterCard)):
                f.update_prop_list(cols, old_n, name_in)
        self.status_label.setText(f"Renamed column '{old_n}' to '{name_in}'.")

    def _retarget_packed_column_store(self, old_n: str, name_in: str) -> None:
        """Keep a renamed poses column's packed cells and ensemble store in sync."""
        import json

        store = getattr(self, "_confs_blocks_sidecar", None)
        if store is not None:
            try:
                keys = [
                    key
                    for key in list(store)
                    if isinstance(key, tuple) and len(key) >= 2 and str(key[1]) == old_n
                ]
            except (TypeError, RuntimeError):
                keys = []
            for key in keys:
                payload = store.get(key)
                if payload is None:
                    continue
                store[(int(key[0]), name_in)] = payload
                try:
                    del store[key]
                except KeyError:
                    continue
        model = getattr(self, "_table_model", None)
        if model is None:
            return
        try:
            n_rows = int(model.rowCount())
        except (TypeError, RuntimeError, ValueError):
            return
        for row in range(n_rows):
            raw = model.backing_value_for_row_header(row, name_in)
            if not raw or old_n not in str(raw):
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or str(payload.get("h") or "") != old_n:
                continue
            payload["h"] = name_in
            oid_text = model.cell_text(row, 0)
            if not str(oid_text).isdigit():
                continue
            model.set_backing_text(
                int(oid_text),
                name_in,
                json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
            )

    def _column_can_toggle_logarithmic(self, header_name: str) -> bool:
        if header_name in ("ID_HIDDEN", "Structure"):
            return False
        if self._table_model.is_pixmap_data_column(header_name):
            return False
        if header_name in getattr(self, "_logarithmic_columns", set()):
            return True
        texts = self._table_model.column_text_by_oid(header_name).values()
        return column_can_apply_log10(texts)

    def _toggle_column_logarithmic(self, header_name: str) -> None:
        if not self._column_can_toggle_logarithmic(header_name):
            return
        logs = getattr(self, "_logarithmic_columns", None)
        if logs is None:
            self._logarithmic_columns = set()
            logs = self._logarithmic_columns
        to_log = header_name not in logs
        current = self._table_model.column_text_by_oid(header_name)
        changed = transform_column_values_log10(current, to_log=to_log)
        if not changed and to_log:
            self.status_label.setText(
                f"Column '{header_name}' has no positive numeric values to convert."
            )
            return
        previous = {oid: current[oid] for oid in changed}
        self._undo_stack.push(
            UndoLogarithmicColumnCommand(
                self,
                header_name,
                to_log=to_log,
                changed_by_oid=changed,
                previous_by_oid=previous,
            )
        )

    def _column_can_apply_precision(self, header_name: str) -> bool:
        if header_name in ("ID_HIDDEN", "Structure"):
            return False
        if self._table_model.is_pixmap_data_column(header_name):
            return False
        texts = self._table_model.column_text_by_oid(header_name).values()
        return column_can_apply_precision(texts)

    def _apply_column_precision(self, header_name: str) -> None:
        if not self._column_can_apply_precision(header_name):
            return
        decimals, ok = QInputDialog.getInt(
            self,
            "Precision",
            f"Decimal places for '{header_name}':",
            2,
            0,
            12,
        )
        if not ok:
            return
        current = self._table_model.column_text_by_oid(header_name)
        changed = transform_column_values_precision(current, decimals=decimals)
        if not changed:
            self.status_label.setText(
                f"Column '{header_name}' already matches {decimals} decimal place(s)."
            )
            return
        previous = {oid: current[oid] for oid in changed}
        self._undo_stack.push(
            UndoPrecisionColumnCommand(
                self,
                header_name,
                decimals=decimals,
                changed_by_oid=changed,
                previous_by_oid=previous,
            )
        )

    def show_row_header_menu(self, pos):
        view_row = self.table.verticalHeader().logicalIndexAt(pos)
        mapped = self._source_cell_from_view_index(self.table.model().index(view_row, 0))
        if mapped is None:
            return
        row = mapped[0]
        menu = QMenu(self)
        dup_act = menu.addAction("Duplicate Row")
        del_act = menu.addAction("Delete Row")
        action = menu.exec_(self.table.verticalHeader().mapToGlobal(pos))
        if action == dup_act:
            cmd = UndoInsertRowCommand(self, row)
            if cmd.is_valid():
                self._undo_stack.push(cmd)

        elif action == del_act:
            t0 = self._table_model.cell_text(row, 0)
            if t0.isdigit():
                self._confirm_and_push_delete_rows([row])

    def show_table_menu(self, pos):
        idx = self.table.indexAt(pos)
        mapped = self._source_cell_from_view_index(idx)
        if mapped is None:
            return
        row, col = mapped
        t0 = self._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None

        menu = QMenu(self)
        packed_confs_b64 = None
        pose_column = False
        if 0 <= col < len(self.headers):
            hdr = self.headers[col]
            raw_cell = self._table_model.backing_value_for_row_header(row, hdr)
            packed_confs_b64 = resolve_blocks_b64_for_viewer(
                raw_cell, hdr, oid, getattr(self, "_confs_blocks_sidecar", {})
            )
            contexts = getattr(self, "_pose_column_contexts", None) or {}
            pose_column = is_poses_header(hdr) or (isinstance(contexts, dict) and hdr in contexts)

        chem_col = self._column_eligible_for_table_chemistry_menu(row, col)
        mol_ctx = self._mol_for_table_context_menu(row, col) if chem_col else None
        sketch_mol = mol_ctx
        depiction_column = depiction_column_for_cell(self, col)
        if sketch_mol is not None and oid is not None and depiction_column:
            from ...chem.depiction_coords import mol_for_app_depiction

            sketch_mol = mol_for_app_depiction(self, sketch_mol, int(oid), depiction_column)

        sketch_act = view_poses_act = view_conformers_act = browser_act = render2d_act = None
        design_act = None
        structure_col = col == CompoundTableModel.STRUCTURE_COL
        open_section = False
        if structure_col and oid is not None:
            sketch_act = menu.addAction("Open in Sketcher")
            sketch_act.setToolTip(
                "Open this row in the sketcher. "
                "Update Table Entry replaces this row. Add to Table adds a new one."
            )
            open_section = True
        elif chem_col and mol_ctx is not None:
            sketch_act = menu.addAction("Open in Sketcher")
            sketch_act.setToolTip(
                "Open this structure in the sketcher. Add to Table adds it as a new row."
            )
            open_section = True
        if chem_col and mol_ctx is not None:
            design_act = menu.addAction("Open in Design Studio")
            design_act.setToolTip(
                "Open this structure in the Design Studio. The table row stays unchanged."
            )
            open_section = True
        if packed_confs_b64 is not None and pose_column:
            view_poses_act = menu.addAction("View Poses")
            open_section = True
        if packed_confs_b64 is not None:
            view_conformers_act = menu.addAction("View Conformers…")
            open_section = True
        if chem_col and mol_ctx is not None and not structure_col:
            render2d_act = menu.addAction(TOOL_RENDER_2D)
            render2d_act.setEnabled(oid is not None)
            open_section = True
        if open_section:
            menu.addSeparator()

        can_copy, copy_text = self._copy_text_for_table_cell(row, col, oid)
        copy_act = None
        copy_format_by_act: dict = {}
        if chem_col:
            copy_format_by_act = self._add_structure_copy_submenu(menu, mol_ctx)
        else:
            copy_act = menu.addAction("Copy")
            copy_act.setEnabled(can_copy)

        can_paste = oid is not None and self._column_accepts_cell_paste(row, col)
        paste_act = menu.addAction("Paste")
        paste_act.setEnabled(can_paste)
        if chem_col and mol_ctx is not None:
            menu.addSeparator()
            browser_act = menu.addAction("Browser…")

        text_editable = self._table_model.column_accepts_text_edit(col)
        edit_act = clear_act = None
        if text_editable:
            menu.addSeparator()
            edit_act = menu.addAction("Edit Value…")
            clear_act = menu.addAction("Clear Value")

        mmp_ledger_act = None
        if 0 <= col < len(self.headers):
            from ...analysis.mmp_table import is_mmp_result_header

            if is_mmp_result_header(self.headers[col]):
                menu.addSeparator()
                mmp_ledger_act = menu.addAction("Transform Ledger")
                mmp_ledger_act.setToolTip(
                    "Open the MMP Transform Ledger for this session's MMP results."
                )

        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if sketch_act is not None and action == sketch_act:
            self.open_sketcher(
                sketch_mol,
                source_oid=oid if structure_col else None,
            )
        elif design_act is not None and action == design_act and mol_ctx is not None:
            opener = getattr(self, "open_design_studio_for_molecule", None)
            if callable(opener):
                opener(sketch_mol)
        elif view_poses_act is not None and action == view_poses_act and oid is not None:
            column = self.headers[col] if 0 <= col < len(self.headers) else ""
            self.show_packed_poses_in_viewer(int(oid), column)
        elif (
            view_conformers_act is not None
            and action == view_conformers_act
            and packed_confs_b64 is not None
        ):
            confs_col = "confs"
            if 0 <= col < len(self.headers):
                hdr = self.headers[col]
                if is_packed_ensemble_header(hdr):
                    confs_col = hdr
            self.open_packed_conformer_viewer(
                packed_confs_b64,
                title="View Conformers",
                export_parent_oid=oid,
                export_confs_column=confs_col,
                source_oid=oid,
            )
        elif browser_act is not None and action == browser_act:
            self.open_selection_browser(focus_oid=oid)
        elif render2d_act is not None and action == render2d_act and mol_ctx is not None:
            self.run_render_2d_for_table_row(row, col)
        elif action is not None and action in copy_format_by_act:
            text, status = copy_format_by_act[action]
            QApplication.clipboard().setText(text)
            self.status_label.setText(status)
        elif copy_act is not None and action == copy_act and can_copy:
            QApplication.clipboard().setText(copy_text)
        elif action == paste_act and can_paste:
            self.edit_paste(origin=(row, col))
        elif edit_act is not None and action == edit_act:
            old_t = self._table_model.cell_text(row, col) or ""
            txt, ok = QInputDialog.getText(self, "Edit value", "New value:", text=old_t)
            if ok and oid is not None:
                h = self.headers[col]
                if txt != old_t:
                    self._undo_stack.push(UndoCellTextChangeCommand(self, int(oid), h, old_t, txt))
        elif clear_act is not None and action == clear_act:
            if oid is not None:
                h = self.headers[col]
                old_t = self._table_model.cell_text(row, col) or ""
                if old_t != "":
                    self._undo_stack.push(UndoCellTextChangeCommand(self, int(oid), h, old_t, ""))
        elif mmp_ledger_act is not None and action == mmp_ledger_act:
            opener = getattr(self, "open_mmp_transform_ledger_for_last_run", None)
            if callable(opener):
                opener()
