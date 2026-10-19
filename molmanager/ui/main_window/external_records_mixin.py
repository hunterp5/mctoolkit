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

"""External DB / PubChem / ChEMBL / vendor / patent query row ingest."""

from __future__ import annotations

import time

from PyQt5.QtCore import QTimer

from rdkit import Chem

from ...platform_support.config import load_config
from ...table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class ExternalRecordsMixin:
    def open_external_db(self):
        from ..external import ExternalDBDialog

        reuse_or_show_modeless_singleton(
            self,
            "_external_db_dialog",
            lambda: ExternalDBDialog(self),
        )

    def open_pubchem(self):
        from ..external import PubChemDialog

        reuse_or_show_modeless_singleton(
            self,
            "_pubchem_dialog",
            lambda: PubChemDialog(self),
        )

    def open_chembl(self):
        from ..external import ChEMBLDialog

        reuse_or_show_modeless_singleton(
            self,
            "_chembl_dialog",
            lambda: ChEMBLDialog(self),
        )

    def open_patent_query(self):
        from ..external import PatentQueryDialog

        reuse_or_show_modeless_singleton(
            self,
            "_patent_query_dialog",
            lambda: PatentQueryDialog(self),
        )

    def open_vendor_query(self):
        from ..external import VendorQueryDialog

        reuse_or_show_modeless_singleton(
            self,
            "_vendor_query_dialog",
            lambda: VendorQueryDialog(self),
        )

    def add_row_from_external_record(self, smiles: str, fields: dict[str, str]) -> None:
        """Append a row with SMILES + additional fields; render structure when possible."""
        smiles = (smiles or "").strip()
        if not smiles:
            raise ValueError("Empty SMILES.")
        self._ensure_columns(["SMILES"] + list(fields.keys()))

        self.table.setSortingEnabled(False)
        oid = self.next_oid
        self.next_oid += 1
        row_cells: dict[str, str] = {}
        for h in self.headers[2:]:
            if h == "SMILES":
                row_cells[h] = smiles
            else:
                row_cells[h] = str(fields.get(h, "") or "")
        self._table_model.append_row(oid, row_cells)

        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            self.mols[oid] = mol
            self.start_render_worker(oid, mol)

        self._sync_global_bounds_for_headers(list(fields.keys()), refresh_filters=False)
        self.table.setSortingEnabled(False)

    def add_rows_from_external_records_batch(
        self,
        records: list[tuple[str, dict[str, str]]],
        *,
        render_structures: bool = True,
    ) -> int:
        """Append many external rows with one model notification (ChEMBL/PubChem/protomer adds)."""
        if not records:
            return 0
        field_names: set[str] = set()
        for _smi, fields in records:
            field_names.update(fields.keys())
        self._ensure_columns(["SMILES"] + sorted(field_names))
        prepared = self._prepare_external_record_rows(records)
        if not prepared:
            return 0
        if len(prepared) == 1 or getattr(self, "_external_append_active", False):
            if len(prepared) > 1 and getattr(self, "_external_append_active", False):
                queue = getattr(self, "_external_append_queue", None)
                if queue is None:
                    self._external_append_queue = []
                    queue = self._external_append_queue
                queue.append((records, render_structures))
                return len(prepared)
            return self._add_external_records_batch_sync(
                prepared, sorted(field_names), render_structures=render_structures
            )
        self._external_append_active = True
        self._external_append_prepared = prepared
        self._external_append_index = 0
        self._external_append_field_names = sorted(field_names)
        self._external_append_render = render_structures
        self.table.setSortingEnabled(False)
        QTimer.singleShot(0, self._process_external_records_append_chunk)
        return len(prepared)

    def _prepare_external_record_rows(
        self, records: list[tuple[str, dict[str, str]]]
    ) -> list[tuple[int, dict[str, str]]]:
        prepared: list[tuple[int, dict[str, str]]] = []
        for smiles, fields in records:
            smiles = (smiles or "").strip()
            if not smiles:
                continue
            oid = self.next_oid
            self.next_oid += 1
            row_cells: dict[str, str] = {}
            for h in self.headers[2:]:
                if h == "SMILES":
                    row_cells[h] = smiles
                else:
                    row_cells[h] = str(fields.get(h, "") or "")
            prepared.append((oid, row_cells))
        return prepared

    def _add_external_records_batch_sync(
        self,
        prepared: list[tuple[int, dict[str, str]]],
        field_names: list[str],
        *,
        render_structures: bool,
    ) -> int:
        """Append external rows immediately (small batches or when a deferred append is active)."""
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        new_mols: list[tuple[int, Chem.Mol]] = []
        if render_structures:
            for oid, row_cells in prepared:
                smi = (row_cells.get("SMILES", "") or "").strip()
                if not smi:
                    continue
                mol = Chem.MolFromSmiles(smi)
                if mol is not None:
                    new_mols.append((oid, mol))
        cfg = load_config()
        defer_color = len(prepared) >= int(cfg.bulk_update_defer_color_cache_rows)
        self._table_model.append_rows_batch(prepared, defer_color_cache=defer_color)
        for oid, mol in new_mols:
            self.mols[oid] = mol
            self.start_render_worker(oid, mol)
        if defer_color:
            self._table_model.rebuild_column_color_caches_after_bulk_load()
        self._sync_global_bounds_for_headers(field_names, refresh_filters=False)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        self.table.setSortingEnabled(False)
        return len(prepared)

    def _process_external_records_append_chunk(self) -> None:
        prepared = getattr(self, "_external_append_prepared", None)
        if not prepared:
            self._external_append_active = False
            return
        cfg = load_config()
        chunk_size = int(cfg.ingest_gui_chunk_size)
        budget_s = max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        deadline = time.monotonic() + budget_s
        start = int(getattr(self, "_external_append_index", 0))
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        batch_rows: list[tuple[int, dict[str, str]]] = []
        while (
            start < len(prepared) and len(batch_rows) < chunk_size and time.monotonic() < deadline
        ):
            batch_rows.append(prepared[start])
            start += 1
        self._external_append_index = start
        if batch_rows:
            self._table_model.append_rows_batch(batch_rows, defer_color_cache=True)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if start < len(prepared):
            QTimer.singleShot(0, self._process_external_records_append_chunk)
        else:
            QTimer.singleShot(0, self._finalize_external_records_append)

    def _finalize_external_records_append(self) -> None:
        prepared = getattr(self, "_external_append_prepared", None) or []
        field_names = list(getattr(self, "_external_append_field_names", []) or [])
        render_structures = bool(getattr(self, "_external_append_render", False))
        oids = [oid for oid, _ in prepared]
        for attr in (
            "_external_append_prepared",
            "_external_append_index",
            "_external_append_field_names",
            "_external_append_render",
        ):
            try:
                delattr(self, attr)
            except AttributeError:
                pass
        self._external_append_active = False
        self.table.setSortingEnabled(False)
        self._table_model.rebuild_column_color_caches_after_bulk_load()
        QTimer.singleShot(
            0,
            lambda: self._sync_global_bounds_for_headers(field_names, refresh_filters=False),
        )
        if render_structures and oids:
            self._external_append_render_oids = list(oids)
            self._external_append_render_tasks = []
            self._external_append_render_row_by_oid = {}
            self._external_append_render_index = 0
            QTimer.singleShot(0, self._external_append_render_tasks_chunk)
        else:
            self._drain_external_append_queue()

    def _external_append_render_tasks_chunk(self) -> None:
        oids = getattr(self, "_external_append_render_oids", None)
        if not oids:
            self._drain_external_append_queue()
            return
        idx = int(getattr(self, "_external_append_render_index", 0))
        chunk = 64
        slice_oids = oids[idx : idx + chunk]
        base_w, base_h = structure_depict_width(), structure_depict_height()
        tasks, row_map = self._build_render2d_tasks_for_oids(slice_oids, base_w, base_h)
        self._external_append_render_tasks.extend(tasks)
        self._external_append_render_row_by_oid.update(row_map)
        idx += len(slice_oids)
        self._external_append_render_index = idx
        if idx < len(oids):
            QTimer.singleShot(0, self._external_append_render_tasks_chunk)
            return
        renders = list(getattr(self, "_external_append_render_tasks", []) or [])
        row_by_oid = dict(getattr(self, "_external_append_render_row_by_oid", {}) or {})
        for attr in (
            "_external_append_render_oids",
            "_external_append_render_tasks",
            "_external_append_render_row_by_oid",
            "_external_append_render_index",
        ):
            try:
                delattr(self, attr)
            except AttributeError:
                pass
        if renders:
            self._start_render_2d_batch(
                renders,
                row_by_oid,
                "Structure",
                column_pixmap_mode=False,
            )
        self._drain_external_append_queue()

    def _drain_external_append_queue(self) -> None:
        queue = getattr(self, "_external_append_queue", None)
        if not queue:
            return
        records, render_structures = queue.pop(0)
        if not queue:
            try:
                delattr(self, "_external_append_queue")
            except AttributeError:
                pass
        self.add_rows_from_external_records_batch(records, render_structures=render_structures)
