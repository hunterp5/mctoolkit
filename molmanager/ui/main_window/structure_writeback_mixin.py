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

"""Job inputs and bulk writeback for structure-prep tools (``WorkspaceTools.structure_prep``).

Tools read stored blobs / cell text on the GUI thread and let workers rebuild molecules;
workers return ``(oid, blob, smiles)`` rows that are written back in one batch. Per-row
``MolStore`` reads and writes froze the GUI for tens of seconds on 100k-row tables.
"""

from __future__ import annotations

from rdkit import Chem

from ...chem.molecule_conversion import mol_from_binary_blob
from ...table.structure_depiction_layout import structure_depict_height, structure_depict_width


class StructureWritebackMixin:
    def _structure_tool_inputs(
        self, src: str, allowed: set[int] | None, *, with_source_text: bool = False
    ) -> list[tuple]:
        """Scoped job inputs for *src* in table order, read without hydrating molecules.

        Rows are ``(oid, blob_or_text)`` for :func:`~molmanager.chem.molecule_conversion.mol_from_tool_input`.
        With *with_source_text* they are ``(oid, blob_or_None, source_text)`` so disconnect
        tools also see the original multi-component cell text.
        """
        rows: list[tuple] = []
        for payload in self.collect_scoped_table_structure_payloads(src, allowed_oids=allowed):
            oid = int(payload.oid)
            if not with_source_text:
                rows.append((oid, payload.blob or payload.smiles))
                continue
            text = payload.smiles
            if src == "Structure":
                text = self._disconnect_source_text_for_oid(oid, src) or text
            rows.append((oid, payload.blob, text))
        return rows

    def _store_structure_blobs(self, rows: list[tuple[int, bytes, str]]) -> None:
        """Replace Structure entries with ``(oid, blob, smiles)`` rows in one store write."""
        ingest = getattr(self.mols, "ingest_jobs", None)
        if callable(ingest):
            ingest(rows)
            return
        for oid, blob, _smiles in rows:
            mol = mol_from_binary_blob(blob)
            if mol is not None:
                self.mols[oid] = mol

    def _write_tool_structures(self, dest: str, rows: list[tuple[int, bytes, str]]) -> list[int]:
        """Write worker ``(oid, blob, smiles)`` rows into *dest*; return the written oids.

        Structure goes to the molecule store; other columns get the SMILES (hidden backing
        text for depiction columns). Stale depictions are dropped so they can be re-rendered.
        """
        model = self._table_model
        oids = [int(oid) for oid, _blob, _smiles in rows]
        depiction = getattr(self, "_depiction_coords", None)
        if depiction is not None and oids:
            depiction.discard_column_oids(dest, oids)
        if dest == "Structure":
            self._store_structure_blobs(rows)
            model.clear_structure_pixmaps_for_oids(oids)
        elif dest in self.headers:
            model.set_column_backing_text_by_oids(
                dest, [(oid, smiles) for oid, _blob, smiles in rows]
            )
            if model.is_pixmap_data_column(dest):
                model.clear_column_pixmaps_for_oids(dest, oids)
        return oids

    def _tool_target_renders_2d(self, dest: str) -> bool:
        return dest == "Structure" or (
            dest in self.headers and self._table_model.is_pixmap_data_column(dest)
        )

    def _render_tool_structures(
        self, dest: str, oids: list[int], *, queue_title_prefix: str = ""
    ) -> bool:
        """Queue 2D redraws of *dest* for *oids*. Return True when a batch started."""
        if not oids or getattr(self, "_render2d_batch_active", False):
            return False
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(
            dest, structure_depict_width(), structure_depict_height(), set(oids)
        )
        if not renders:
            return False
        self._start_render_2d_batch(
            renders,
            row_by_oid,
            dest,
            column_pixmap_mode=dest != "Structure",
            queue_title_prefix=queue_title_prefix,
        )
        return True

    def _apply_mol_tool_results(
        self,
        results,
        *,
        src: str,
        no_render_2d: bool,
        done_label: str = "Done.",
    ) -> None:
        """Write ``(oid, blob, smiles)`` tool results into *src*, then optionally render 2D."""
        rows = [(int(oid), bytes(blob), smiles) for oid, blob, smiles in results if blob]
        oids = self._write_tool_structures(src, rows)
        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()
        if not no_render_2d and self._tool_target_renders_2d(src):
            if self._render_tool_structures(src, oids):
                return
        self.status_label.setText(self._consume_partial_results_notice() or done_label)

    def _mol_for_structure_tool_oid(self, oid: int, src: str) -> Chem.Mol | None:
        """Molecule for one row and source column (single-row callers only; hydrates)."""
        row = self.logical_row_for_oid(oid)
        if row < 0:
            return None
        if src == "Structure":
            return self.mols.get(oid)
        if src not in self.headers:
            return None
        col = self.headers.index(src)
        raw = ""
        if self._table_model.is_pixmap_data_column(src):
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        else:
            raw = (self._table_cell_text(row, col) or "").strip()
            if not raw:
                raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        if not raw:
            return None
        return self._mol_from_structure_text(raw)

    def _disconnect_source_text_for_oid(self, oid: int, src: str) -> str | None:
        """Original cell text for the disconnect target column (for multi-component SMILES)."""
        row = self.logical_row_for_oid(oid)
        if row < 0:
            return None
        if src == "Structure":
            return self._structure_text_for_oid(oid) or None
        if src in self.headers and self._table_model.is_pixmap_data_column(src):
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
            return raw or None
        col = self.headers.index(src)
        raw = (self._table_cell_text(row, col) or "").strip()
        if not raw:
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        return raw or None

    def _ensure_disconnect_output_column(self, header_name: str) -> None:
        """Insert a data column if the disconnect dialog named one that is not present yet."""
        if not header_name or header_name in self.headers:
            return
        if header_name == "Fragments" and "Salt" in self.headers:
            idx_old = self.headers.index("Salt")
            self.headers[idx_old] = "Fragments"
            self._table_model.rename_header_at(idx_old, "Fragments")
            return
        nc = self._table_model.columnCount()
        self.headers.append(header_name)
        self._table_model.insert_column_at(nc, header_name, None)
