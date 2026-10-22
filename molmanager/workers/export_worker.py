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

"""Export table + molecules to disk."""

import csv
import logging
import threading

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..table.table_file_formats import write_openbabel_mols, write_xlsx_table
from ..chem.molecule_conversion import mol_to_canonical_smiles

logger = logging.getLogger(__name__)


def _row_with_smiles(row: dict, mol) -> dict | None:
    out = dict(row or {})
    if not str(out.get("SMILES", "") or "").strip():
        if mol is not None:
            out["SMILES"] = mol_to_canonical_smiles(mol)
        else:
            return None
    return out


class ExportWorker(QRunnable):
    def __init__(
        self,
        path,
        ext,
        mols_dict,
        headers_to_export,
        table_data,
        signals,
        cancel_event: threading.Event | None = None,
        oids: list[int] | None = None,
    ):
        super().__init__()
        self.path, self.ext, self.mols, self.headers, self.table_data, self.signals = (
            path,
            ext,
            mols_dict,
            headers_to_export,
            table_data,
            signals,
        )
        self.cancel_event = cancel_event
        if oids is not None:
            self.oids = [int(x) for x in oids]
        else:
            self.oids = [int(k) for k in (table_data or {}).keys()]

    def run(self):
        user_cancelled = False
        try:
            skip = ["ID_HIDDEN", "Structure"]
            clean_headers = [h for h in self.headers if h not in skip]
            mols = self.mols or {}
            oid_list = self.oids or [int(k) for k in (self.table_data or {}).keys()]
            tot = max(len(oid_list), 1)
            ext = (self.ext or "").lower()

            def _mol_and_row(oid: int):
                mol = mols.get(oid)
                row = self.table_data.get(oid, {})
                if mol is None:
                    smi = str(row.get("SMILES", "") or "").strip()
                    if smi:
                        mol = Chem.MolFromSmiles(smi)
                return mol, row

            if ext in {".csv", ".tsv"}:
                csv_heads = clean_headers.copy()
                if "SMILES" not in csv_heads:
                    csv_heads.insert(0, "SMILES")
                delim = "\t" if ext == ".tsv" else ","
                with open(self.path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=csv_heads, delimiter=delim)
                    writer.writeheader()
                    for done, oid in enumerate(oid_list, start=1):
                        if self.cancel_event is not None and self.cancel_event.is_set():
                            user_cancelled = True
                            break
                        mol, row = _mol_and_row(oid)
                        filled = _row_with_smiles(row, mol)
                        if filled is None:
                            continue
                        writer.writerow({k: v for k, v in filled.items() if k in csv_heads})
                        try:
                            self.signals.tool_progress.emit("Exporting…", done, tot)
                        except Exception:
                            pass
            elif ext == ".xlsx":
                csv_heads = clean_headers.copy()
                if "SMILES" not in csv_heads:
                    csv_heads.insert(0, "SMILES")
                rows: list[dict[str, str]] = []
                for done, oid in enumerate(oid_list, start=1):
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        user_cancelled = True
                        break
                    mol, row = _mol_and_row(oid)
                    filled = _row_with_smiles(row, mol)
                    if filled is None:
                        continue
                    rows.append({k: filled.get(k, "") for k in csv_heads})
                    try:
                        self.signals.tool_progress.emit("Exporting…", done, tot)
                    except Exception:
                        pass
                if not user_cancelled:
                    write_xlsx_table(self.path, csv_heads, rows)
            elif ext in {".mol2", ".pdbqt"}:
                fmt = "mol2" if ext == ".mol2" else "pdbqt"
                out_mols: list = []
                for done, oid in enumerate(oid_list, start=1):
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        user_cancelled = True
                        break
                    mol, row = _mol_and_row(oid)
                    if mol is None:
                        continue
                    out_mol = Chem.Mol(mol)
                    for h in clean_headers:
                        out_mol.SetProp(h, str(row.get(h, "")))
                    out_mols.append(out_mol)
                    try:
                        self.signals.tool_progress.emit("Exporting…", done, tot)
                    except Exception:
                        pass
                if not user_cancelled:
                    write_openbabel_mols(self.path, out_mols, fmt)
            else:
                if ext in {".sdf", ".sd", ".mol"}:
                    writer = Chem.SDWriter(self.path)
                elif ext == ".smi":
                    writer = Chem.SmilesWriter(self.path)
                elif ext == ".tdt":
                    writer = Chem.TDTWriter(self.path)
                elif ext == ".pdb":
                    writer = Chem.PDBWriter(self.path)
                else:
                    raise ValueError(f"Unsupported export format: {ext or '(none)'}")
                for done, oid in enumerate(oid_list, start=1):
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        user_cancelled = True
                        break
                    mol, row = _mol_and_row(oid)
                    if mol is None:
                        continue
                    out_mol = Chem.Mol(mol)
                    for h in clean_headers:
                        out_mol.SetProp(h, str(row.get(h, "")))
                    writer.write(out_mol)
                    try:
                        self.signals.tool_progress.emit("Exporting…", done, tot)
                    except Exception:
                        pass
                writer.close()
            if user_cancelled:
                self.signals.export_finished.emit("Export cancelled (partial file may exist).")
            else:
                self.signals.export_finished.emit(f"Exported successfully to {self.path}")
        except Exception as e:
            logger.exception("ExportWorker failed for %s", self.path)
            self.signals.export_finished.emit(f"Export Error: {str(e)}")
