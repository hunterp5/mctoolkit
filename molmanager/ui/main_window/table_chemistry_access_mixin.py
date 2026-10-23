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

"""Chemistry column / molecule lookup helpers for the main table."""

from __future__ import annotations

from rdkit import Chem

from ...chem.structure_source_headers import (
    header_looks_like_structure_text,
)
from ...services.chemistry_columns import (
    canonical_smiles_header_for_updates,
    cell_texts_have_parseable_molecule,
    data_headers_confirmed_for_chemistry_tools,
    is_smiles_named_header,
    skip_chemistry_tool_column_dropdown,
    should_skip_chemical_scan_column,
)
from ...services.table_scope import collect_scoped_pairs, resolve_structure_row_for_oid
from ...chem.molecule_conversion import (
    looks_like_mol_block,
    parse_molecule_from_cell_text,
    row_cells_from_mol,
)
from ...chem.structure_payload import (
    StructurePayload,
    mols_from_payloads,
)
from ..compound_table_model import CompoundTableModel


class TableChemistryAccessMixin:
    """Resolve molecules from table cells and chemistry-tool source columns."""

    @staticmethod
    def _header_looks_structural(name: str) -> bool:
        return header_looks_like_structure_text(name)

    def _skip_chemistry_tool_column_dropdown(self, h: str) -> bool:
        """Exclude non-molecular columns from chemistry-tool source dropdowns."""
        return skip_chemistry_tool_column_dropdown(h)

    def _column_has_parseable_molecule_sample(
        self,
        header_name: str,
        *,
        max_rows_scan: int = 500,
        max_nonempty_samples: int = 80,
    ) -> bool:
        """True if a sample of cells in this column parses as a molecule (SMILES, InChI, MolBlock, SMARTS, …)."""
        if header_name not in self.headers:
            return False

        def _iter_texts():
            n = min(self._table_model.rowCount(), max_rows_scan)
            for r in range(n):
                raw = self._table_model.backing_value_for_row_header(r, header_name)
                if not raw:
                    try:
                        ci = self.headers.index(header_name)
                    except ValueError:
                        continue
                    raw = (self._table_cell_text(r, ci) or "").strip()
                yield raw

        return cell_texts_have_parseable_molecule(
            _iter_texts(),
            max_nonempty_samples=max_nonempty_samples,
        )

    def _data_headers_confirmed_for_chemistry_tools(self) -> list[str]:
        """
        Data columns suitable as chemistry-tool sources: structural-looking names,
        or at least one parseable cell in a bounded scan.
        """
        return data_headers_confirmed_for_chemistry_tools(
            self.headers,
            column_has_parseable_sample=self._column_has_parseable_molecule_sample,
        )

    def _should_skip_chemical_scan_column(self, h: str) -> bool:
        return should_skip_chemical_scan_column(
            h,
            is_pixmap_column=self._table_model.is_pixmap_data_column,
        )

    def _canonical_smiles_header_for_updates(self) -> str | None:
        """Column to store canonical SMILES after chemistry tools (prefer ``SMILES``)."""
        return canonical_smiles_header_for_updates(self.headers)

    def _is_smiles_named_header(self, h: str) -> bool:
        return is_smiles_named_header(h)

    def _fill_row_data_columns_from_mol(self, row_idx: int, mol: Chem.Mol | None) -> None:
        """Populate data columns (from col 2 onward) from RDKit mol properties — same source as RenderWorker props."""
        if not self.headers or row_idx < 0 or row_idx >= self._table_model.rowCount():
            return
        oid = self._table_model.row_oid(row_idx)
        values = self._row_cells_from_mol(mol)
        self._table_model.set_cell_text_batch(oid, values)

    def _row_cells_from_mol(self, mol: Chem.Mol | None) -> dict[str, str]:
        """Build row cell values for all data columns from one molecule."""
        return row_cells_from_mol(mol, self.headers[2:])

    def _structure_text_for_oid(self, oid: int) -> str:
        """The row's structure text from the molecule store (what the Structure cell shows)."""
        store = self.mols
        lookup = getattr(store, "structure_text_for", None)
        if callable(lookup):
            return lookup(int(oid))
        mol = store.get(int(oid))
        if mol is None:
            return ""
        try:
            return Chem.MolToSmiles(mol)
        except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
            return ""

    def _mol_for_structure_row(self, row: int) -> Chem.Mol | None:
        """The row's molecule from the molecule store, or ``None`` when it has no structure."""
        if row < 0 or row >= self._table_model.rowCount():
            return None
        return self.mols.get(self._table_model.row_oid(row))

    def _column_eligible_for_table_chemistry_menu(self, row: int, col: int) -> bool:
        """Whether the table cell's column should offer structure tools / Copy formats."""
        if col == CompoundTableModel.STRUCTURE_COL:
            return True
        if col <= 0 or col >= len(self.headers):
            return False
        h = self.headers[col]
        if self._skip_chemistry_tool_column_dropdown(h):
            return False
        if self._header_looks_structural(h) or self._is_smiles_named_header(h):
            return True
        raw = self._structure_text_for_table_cell(row, col)
        if not raw or (len(raw) > 20000 and not looks_like_mol_block(raw)):
            return False
        return parse_molecule_from_cell_text(raw) is not None

    def _column_accepts_cell_paste(self, row: int, col: int) -> bool:
        """Whether Paste is allowed on this cell (text data, Structure, or pixmap chemistry)."""
        if col == CompoundTableModel.STRUCTURE_COL:
            return True
        if self._table_model.column_accepts_text_edit(col):
            return True
        if 0 <= col < len(self.headers) and self._table_model.is_pixmap_data_column(
            self.headers[col]
        ):
            return self._column_eligible_for_table_chemistry_menu(row, col)
        return False

    def _structure_text_for_table_cell(self, row: int, col: int) -> str:
        """Stored SMILES/molblock for a cell, including pixmap-only structure columns."""
        if col == CompoundTableModel.STRUCTURE_COL or col <= 0 or col >= len(self.headers):
            return ""
        h = self.headers[col]
        raw = (self._table_model.backing_value_for_row_header(row, h) or "").strip()
        if raw:
            return raw
        return (self._table_model.cell_text(row, col) or "").strip()

    def _mol_for_table_context_menu(self, row: int, col: int) -> Chem.Mol | None:
        """Molecule for context-menu actions from the clicked column (not a different field)."""
        if not self._column_eligible_for_table_chemistry_menu(row, col):
            return None
        if col == CompoundTableModel.STRUCTURE_COL:
            return self._mol_for_structure_row(row)
        raw = self._structure_text_for_table_cell(row, col)
        if not raw or (len(raw) > 20000 and not looks_like_mol_block(raw)):
            return None
        return self._mol_from_structure_text(raw)

    def _mol_from_structure_text(self, raw: str) -> Chem.Mol | None:
        return parse_molecule_from_cell_text(raw)

    def chemistry_tool_structure_sources(self) -> list[str]:
        """Candidate values for a tool dialog's structure-source dropdown."""
        return ["Structure"] + self._data_headers_confirmed_for_chemistry_tools()

    def _scoped_row_filters(
        self, *, only_selected: bool, only_visible: bool
    ) -> tuple[set[int] | None, set[int] | None]:
        allowed = self._selected_oids_set() if only_selected else None
        visible_rows: set[int] | None = None
        if only_visible:
            vis = self._visible_source_row_indices()
            visible_rows = None if vis is None else set(vis)
        return allowed, visible_rows

    def _plain_store_structure_payloads(
        self, allowed: set[int] | None
    ) -> list[tuple[int, bytes | None, str]]:
        """``(oid, blob, smiles)`` from a plain-dict mol store (tests, legacy sessions)."""
        rows: list[tuple[int, bytes | None, str]] = []
        oids = list(self.mols) if allowed is None else [o for o in allowed if o in self.mols]
        for oid in oids:
            mol = self.mols.get(oid)
            if mol is None:
                continue
            try:
                blob = mol.ToBinary()
            except (AttributeError, RuntimeError):
                continue
            rows.append((int(oid), bytes(blob) if blob else None, ""))
        return rows

    def collect_scoped_table_structure_payloads(
        self,
        src: str,
        *,
        only_selected: bool = False,
        only_visible: bool = False,
        allowed_oids: set[int] | None = None,
    ) -> list[StructurePayload]:
        """Copy ``(oid, blob, smiles)`` in scope without hydrating RDKit molecules.

        ``src`` is ``"Structure"`` (the molecule store's blob and structure text) or a
        data-column header (cell / pixmap backing text only). ``allowed_oids`` narrows the
        scope to those ids and replaces ``only_selected``. Rows come back in table order.
        Callers that need live mols should hydrate on a worker with :func:`mols_from_payloads`.
        """
        allowed, visible_rows = self._scoped_row_filters(
            only_selected=only_selected and allowed_oids is None, only_visible=only_visible
        )
        if allowed_oids is not None:
            allowed = set(allowed_oids)
        store_map: dict[int, tuple[bytes | None, str]] = {}
        if src == "Structure":
            scoped_fn = getattr(self.mols, "structure_payloads_for", None)
            iter_fn = getattr(self.mols, "iter_structure_payloads", None)
            if allowed is not None and callable(scoped_fn):
                rows = scoped_fn(allowed)
            elif callable(iter_fn):
                rows = iter_fn()
            else:
                rows = self._plain_store_structure_payloads(allowed)
            for oid, blob, smi in rows:
                store_map[int(oid)] = (blob, smi or "")
        col = None if src == "Structure" else self.headers.index(src)
        is_pixmap_src = src != "Structure" and self._table_model.is_pixmap_data_column(src)

        def _cell(r: int) -> str:
            raw = (self._table_model.backing_value_for_row_header(r, src) or "").strip()
            if raw or is_pixmap_src:
                return raw
            return (self._table_cell_text(r, col) or "").strip()

        def _resolve(r: int, oid: int) -> StructurePayload | None:
            if src == "Structure":
                blob, smi = store_map.get(int(oid), (None, ""))
                smi = (smi or "").strip()
                if blob or smi:
                    return StructurePayload(int(oid), blob, smi)
                return None
            raw = _cell(r)
            if not raw:
                return None
            return StructurePayload(int(oid), None, raw)

        pairs = collect_scoped_pairs(
            self._table_model.rowCount(),
            row_oid=self._table_model.row_oid,
            resolve=_resolve,
            allowed_oids=allowed,
            visible_rows=visible_rows,
        )
        return [payload for _oid, payload in pairs]

    def collect_scoped_table_mols(
        self,
        src: str,
        *,
        only_selected: bool = False,
        only_visible: bool = False,
    ) -> list[tuple[int, Chem.Mol]]:
        """
        Iterate the table and return ``(oid, mol)`` pairs in scope for a chemistry tool.

        Prefer :meth:`collect_scoped_table_structure_payloads` plus worker-side hydrate
        for queued jobs. This path still hydrates on the caller thread (tests / small tools).
        """
        payloads = self.collect_scoped_table_structure_payloads(
            src, only_selected=only_selected, only_visible=only_visible
        )
        rows: list[tuple[int, Chem.Mol]] = []
        for oid, mol in mols_from_payloads(payloads):
            if oid is None:
                continue
            rows.append((int(oid), mol))
        return rows

    def logical_row_for_oid(self, oid: int) -> int:
        """Return the logical table row for a compound OID, or -1 if missing."""
        return self._table_model.logical_row_for_oid(int(oid))

    def _resolve_structure_row_for_oid(self, oid: int) -> int:
        """Table row index for this molecule id (stable during a Render 2D batch)."""
        return resolve_structure_row_for_oid(
            oid,
            row_count=self._table_model.rowCount(),
            cell_text_col0=lambda r: self._table_model.cell_text(r, 0),
            logical_row_for_oid=self.logical_row_for_oid,
            render2d_row_by_oid=getattr(self, "_render2d_row_by_oid", None),
        )
