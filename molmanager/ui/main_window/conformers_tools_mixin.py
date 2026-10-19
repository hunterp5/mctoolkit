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


"""Conformer generation, superposition, and packed-ensemble writeback."""

from __future__ import annotations


from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMessageBox,
)

from rdkit import Chem

import logging

from ...conformers.conformer_output import write_conformer_results_to_sdf
from ...conformers.conformer_column_codec import (
    rehydrate_v1_confs_cell,
    unpack_confs_blocks_json_b64,
)
from ...workers import (
    ConforgeConformerWorker,
    ConformerGenerationWorker,
    SuperposeConformersWorker,
    SuperposeStructuresWorker,
    SystematicConformerWorker,
)
from ..analysis_job_support import enqueue_process_queue_job

logger = logging.getLogger(__name__)


def _result_oids(results: list) -> list[int]:
    oids: list[int] = []
    for item in results or ():
        if not item:
            continue
        try:
            oids.append(int(item[0]))
        except (TypeError, ValueError, IndexError):
            continue
    return oids


class ConformersToolsMixin:
    def open_generate_conformations(self):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Generate Conformations",
                "Open a file or add rows so the table has molecules to process.",
            )
            return
        from ..dialogs import GenerateConformationsDialog

        d = GenerateConformationsDialog(len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_generate_conformations_dialog_accepted(dlg))
        d.show()

    def open_systematic_conformations(self):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Generate Conformations — Systematic",
                "Open a file or add rows so the table has molecules to process.",
            )
            return
        from ..dialogs import SystematicConformationsDialog

        d = SystematicConformationsDialog(len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_systematic_conformations_dialog_accepted(dlg))
        d.show()

    def open_conforge_conformations(self):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Generate Conformations — CONFORGE",
                "Open a file or add rows so the table has molecules to process.",
            )
            return
        from ..dialogs import ConforgeConformationsDialog

        d = ConforgeConformationsDialog(len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_conforge_conformations_dialog_accepted(dlg))
        d.show()

    def open_pharmacophore_screen(self, pharmacophore_path: str = ""):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Screen Pharmacophore",
                "Open a file or add rows so the table has molecules to screen.",
            )
            return None
        from ..dialogs.pharmacophore_screen import PharmacophoreScreenDialog

        path = (pharmacophore_path or "").strip()
        if not path:
            protein = getattr(self, "_live_protein_viewer", lambda: None)()
            getter = getattr(protein, "pharmacophore_file_for_gnina", None) if protein else None
            path = getter() if callable(getter) else ""
        dlg = PharmacophoreScreenDialog(self, pharmacophore_path=path or "")
        self._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def _collect_mols_for_conformer_tools(self, *, only_selected: bool) -> list[tuple]:
        """Structure ``(oid, blob_or_text)`` inputs; conformer workers rebuild the molecules."""
        allowed = self._selected_oids_set() if only_selected else None
        return self._structure_tool_inputs("Structure", allowed)

    def _on_generate_conformations_dialog_accepted(self, d) -> None:
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Generate Conformations"):
            return
        data = self._collect_mols_for_conformer_tools(only_selected=only_selected)
        if not data:
            QMessageBox.information(
                self,
                "Generate Conformations",
                "No parseable structures for those rows (in-memory molecules or chemistry in table cells).",
            )
            return
        params = d.params()
        self._conformer_output_options = d.output_options()
        self._pending_conformer_initial_superpose = bool((params.align_pattern or "").strip())
        n = len(data)
        from ...platform_support.memory_guards import check_conformer_workload

        guard = check_conformer_workload(n, int(getattr(params, "num_confs", 1) or 1))
        if not guard.ok:
            QMessageBox.warning(self, "Generate Conformations", guard.message)
            return
        from ...workers import StrainEnergyParams

        self._pending_strain_params = StrainEnergyParams(
            force_field=str(params.force_field or "MMFF94s")
        )
        enqueue_process_queue_job(
            self,
            "Generate conformations",
            n,
            lambda ev, ps, d=data, p=params, sigs=self.signals: ConformerGenerationWorker(
                d, p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"Generate conformations ({n} structures)",
        )

    def _on_systematic_conformations_dialog_accepted(self, d) -> None:
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(
            only_selected, allowed, "Generate Conformations — Systematic"
        ):
            return
        data = self._collect_mols_for_conformer_tools(only_selected=only_selected)
        if not data:
            QMessageBox.information(
                self,
                "Generate Conformations — Systematic",
                "No parseable structures for those rows (in-memory molecules or chemistry in table cells).",
            )
            return
        params = d.params()
        from ...conformers.openbabel_confab import ensure_openbabel_confab_ready

        missing = ensure_openbabel_confab_ready(params.obabel_path)
        if missing:
            QMessageBox.warning(self, "Generate Conformations — Systematic", missing)
            return
        self._conformer_output_options = d.output_options()
        self._pending_conformer_initial_superpose = False
        n = len(data)
        from ...platform_support.memory_guards import check_conformer_workload

        guard = check_conformer_workload(n, int(getattr(params, "num_confs", 1) or 1))
        if not guard.ok:
            QMessageBox.warning(self, "Generate Conformations — Systematic", guard.message)
            return
        from ...workers import StrainEnergyParams

        self._pending_strain_params = StrainEnergyParams(force_field="MMFF")
        enqueue_process_queue_job(
            self,
            "Systematic conformations",
            n,
            lambda ev, ps, d=data, p=params, sigs=self.signals: SystematicConformerWorker(
                d, p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"Systematic conformations ({n} structures)",
        )

    def _on_conforge_conformations_dialog_accepted(self, d) -> None:
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(
            only_selected, allowed, "Generate Conformations — CONFORGE"
        ):
            return
        data = self._collect_mols_for_conformer_tools(only_selected=only_selected)
        if not data:
            QMessageBox.information(
                self,
                "Generate Conformations — CONFORGE",
                "No parseable structures for those rows (in-memory molecules or chemistry in table cells).",
            )
            return
        params = d.params()
        from ...conformers.conforge_generation import ensure_conforge_ready

        missing = ensure_conforge_ready(params.confgen_path)
        if missing:
            QMessageBox.warning(self, "Generate Conformations — CONFORGE", missing)
            return
        self._conformer_output_options = d.output_options()
        self._pending_conformer_initial_superpose = False
        n = len(data)
        from ...platform_support.memory_guards import check_conformer_workload

        guard = check_conformer_workload(n, max(1, int(getattr(params, "num_confs", 1) or 1)))
        if not guard.ok:
            QMessageBox.warning(self, "Generate Conformations — CONFORGE", guard.message)
            return
        from ...workers import StrainEnergyParams

        self._pending_strain_params = StrainEnergyParams(force_field="MMFF")
        enqueue_process_queue_job(
            self,
            "CONFORGE conformations",
            n,
            lambda ev, ps, d=data, p=params, sigs=self.signals: ConforgeConformerWorker(
                d, p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"CONFORGE conformations ({n} structures)",
        )

    def cancel_active_tool_process(self) -> None:
        """Request cooperative cancellation of the process-queue job, Render 2D, and/or Gnina."""
        r2d = self.cancel_render_2d_batch()
        gnina = self.cancel_gnina_dock()
        pq_ok = self.process_queue.cancel_running()
        if pq_ok:
            self.status_label.setText("Cancelling…")
        elif r2d:
            self.status_label.setText("Render 2D cancelled.")
        elif gnina:
            self.status_label.setText("Gnina stopped.")
        else:
            QMessageBox.information(
                self,
                "Cancel Process",
                "Nothing to cancel (no process-queue job, Render 2D batch, or Gnina run), "
                "or cancellation was already requested.",
            )

    def on_conformers_finished(self, results: list) -> None:
        self._finish_tool_progress(status_message=None)
        self.status_label.setText("Writing conformer results…")
        output_opts = getattr(self, "_conformer_output_options", None)
        self._conformer_output_options = None
        added_rows = 0
        saved_count = 0
        confs_col = "confs"
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            confs_col = self._next_packed_ensemble_column("confs", _result_oids(results))
            self._write_ensemble_worker_results(confs_col, results)
            if output_opts is not None and output_opts.add_to_table:
                added_rows = self._append_generated_conformers_as_rows(results)
            if output_opts is not None and output_opts.save_to_file and output_opts.save_path:
                try:
                    saved_count = write_conformer_results_to_sdf(output_opts.save_path, results)
                except OSError as e:
                    QMessageBox.warning(
                        self, "Generate Conformations", f"Could not write SDF file:\n{e}"
                    )
            self.schedule_calculate_global_bounds()
            self.table.setSortingEnabled(False)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        notice = self._consume_partial_results_notice()
        parts = []
        if notice:
            parts.append(notice)
        if confs_col != "confs":
            parts.append(f"Wrote ensembles to “{confs_col}”.")
        if output_opts is not None and output_opts.add_to_table:
            parts.append(f"Added {added_rows} conformer row(s) to the table.")
        if output_opts is not None and output_opts.save_to_file and output_opts.save_path:
            if saved_count:
                parts.append(f"Wrote {saved_count} conformer(s) to {output_opts.save_path}.")
            elif not any(p.startswith("Could not") for p in parts):
                parts.append("No conformers were written to the SDF file.")
        self.status_label.setText(" ".join(parts) if parts else "Done.")
        initial_superpose = bool(getattr(self, "_pending_conformer_initial_superpose", False))
        self._pending_conformer_initial_superpose = False
        n_ok = self._auto_open_first_conformer_results(
            results,
            title="View Conformers",
            confs_column=confs_col,
            initial_superpose=initial_superpose,
        )
        self._pending_strain_params = None
        if n_ok > 1:
            self.status_label.setText(
                (self.status_label.text() + " " if self.status_label.text() else "")
                + f"Opened energy results for the first of {n_ok} ensembles; "
                "use View Conformers on other rows."
            )

    def _append_generated_conformers_as_rows(self, results: list) -> int:
        """Append one table row per generated conformer; keep 3D coordinates in ``self.mols``."""
        from .conformer_writeback import append_generated_conformers_as_rows

        return append_generated_conformers_as_rows(self, results)

    def export_conformer_viewer_to_table(
        self,
        *,
        blocks_json_b64: str,
        conf_indices: list[int] | None = None,
        strain_overlay: dict | None = None,
        parent_oid: int | None = None,
        confs_column: str = "confs",
    ) -> int:
        """
        Append viewer conformer(s) as table rows.

        Structure gets a 2D depiction; 3D coordinates are packed into *confs_column*
        (created if missing) so View Conformers works again. When *strain_overlay*
        is present, also writes ``E_kcal``, ``(delta)E_kcal``, and ``RMSD``.
        """
        from .conformer_writeback import export_conformer_viewer_to_table

        return export_conformer_viewer_to_table(
            self,
            blocks_json_b64=blocks_json_b64,
            conf_indices=conf_indices,
            strain_overlay=strain_overlay,
            parent_oid=parent_oid,
            confs_column=confs_column,
        )

    def open_superpose(self, default_target: str | None = None):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Superpose",
                "Open a file or add rows so the table has data to process.",
            )
            return
        from ..dialogs import SuperposeDialog

        has_confs = "confs" in self.headers
        target = (default_target or "").strip().lower()
        if target not in {"conformers", "structures"}:
            target = "conformers" if has_confs else "structures"
        sources = ["Structure"] + [c for c in ("confs", "superpose") if c in self.headers]
        d = SuperposeDialog(
            len(self._selected_logical_rows()),
            source_columns=sources,
            has_confs=has_confs,
            default_target=target,
            parent=self,
        )
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_superpose_dialog_accepted(dlg))
        d.show()

    def _on_superpose_dialog_accepted(self, d) -> None:
        if d.target() == "conformers":
            self._run_superpose_conformers(d)
        else:
            self._run_superpose_structures(d)

    def open_superpose_conformers(self):
        self.open_superpose(default_target="conformers")

    def open_superpose_structures(self):
        self.open_superpose(default_target="structures")

    def _run_superpose_conformers(self, d) -> None:
        if "confs" not in self.headers:
            QMessageBox.information(
                self,
                "Superpose",
                'Add a "confs" column first by running Generate Conformations (packed multi-conformer cells).',
            )
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Superpose"):
            return
        from ...storage import EnsembleStore, ensemble_db_path

        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        store = getattr(self, "_confs_blocks_sidecar", None)
        db_path = str(ensemble_db_path(self) or "") or None
        data: list[tuple[int, str]] = []
        for o in oids_list:
            r = self.logical_row_for_oid(o)
            if r < 0:
                continue
            if isinstance(store, EnsembleStore) and (int(o), "confs") in store:
                data.append((int(o), "confs"))
                continue
            raw = self._table_model.backing_value_for_row_header(r, "confs")
            sc = store if store is not None else {}
            full = rehydrate_v1_confs_cell(raw, "confs", int(o), sc)
            if unpack_confs_blocks_json_b64(full) is None:
                continue
            data.append((int(o), full))
        if not data:
            QMessageBox.information(
                self,
                "Superpose",
                'No rows in scope have a packed multi-conformer "confs" cell. Run Generate Conformations first.',
            )
            return
        params = d.conformer_params()
        from ...workers import StrainEnergyParams

        if str(getattr(params, "geometry", "3d") or "3d").lower().startswith("2"):
            self._pending_strain_params = None
        else:
            self._pending_strain_params = StrainEnergyParams(
                reference_conformer_index=int(params.reference_conformer_index or 0)
            )
        n = len(data)
        enqueue_process_queue_job(
            self,
            "Superpose",
            n,
            lambda ev, ps, d=data, p=params, sigs=self.signals, db=db_path: (
                SuperposeConformersWorker(
                    d, p, sigs, cancel_event=ev, progress_state=ps, ensemble_db=db
                )
            ),
            queue_label=f"Superpose ({n} rows)",
        )

    def on_superpose_finished(self, results: list) -> None:
        self._finish_tool_progress("Superpose", status_message=None)
        self.status_label.setText("Writing superpose results…")
        superpose_col = "superpose"
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            superpose_col = self._next_packed_ensemble_column("superpose", _result_oids(results))
            self._write_ensemble_worker_results(superpose_col, results)
            self.schedule_calculate_global_bounds()
            self.table.setSortingEnabled(False)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        notice = self._consume_partial_results_notice()
        parts = []
        if notice:
            parts.append(notice)
        if superpose_col != "superpose":
            parts.append(f"Wrote overlays to “{superpose_col}”.")
        self.status_label.setText(" ".join(parts) if parts else "Done.")
        n_ok = self._auto_open_first_conformer_results(
            results,
            title="Superpose",
            confs_column=superpose_col,
            initial_superpose=True,
        )
        self._pending_strain_params = None
        if n_ok > 1:
            self.status_label.setText(
                (self.status_label.text() + " " if self.status_label.text() else "")
                + f"Opened energy results for the first of {n_ok} overlays; "
                "use View Conformers on other rows."
            )

    def _mol_3d_for_structure_superpose(self, oid: int, src: str) -> Chem.Mol | None:
        """Best-effort 3D mol for structure superposition from *src* (Structure / confs / …)."""
        from .conformer_writeback import mol_3d_for_structure_superpose

        return mol_3d_for_structure_superpose(self, oid, src)

    def _mol_for_structure_superpose(
        self, oid: int, src: str, *, geometry: str = "3d"
    ) -> Chem.Mol | None:
        """Molecule for structure superposition; 2D does not require 3D coordinates."""
        from .conformer_writeback import mol_for_structure_superpose

        return mol_for_structure_superpose(self, oid, src, geometry=geometry)

    def _run_superpose_structures(self, d) -> None:
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Superpose"):
            return
        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        if len(oids_list) < 2:
            QMessageBox.information(
                self,
                "Superpose",
                "Select at least two rows (Selected Rows Only) to superpose structures.",
            )
            return
        src = d.source_column()
        params = d.structure_params()
        geom = str(getattr(params, "geometry", "3d") or "3d")
        probes: list[tuple[int, Chem.Mol]] = []
        for o in oids_list:
            m = self._mol_for_structure_superpose(int(o), src, geometry=geom)
            if m is None:
                continue
            probes.append((int(o), m))
        if len(probes) < 2:
            need = "2D structures" if str(geom).lower().startswith("2") else "3D structures"
            QMessageBox.information(
                self,
                "Superpose",
                f"Need at least two rows with usable {need} in scope.",
            )
            return
        ref_oid, ref_mol = probes[0]
        n = len(probes)
        enqueue_process_queue_job(
            self,
            "Superpose",
            n,
            lambda ev, ps, rid=ref_oid, rm=ref_mol, pr=probes, p=params, sigs=self.signals: (
                SuperposeStructuresWorker(rid, rm, pr, p, sigs, cancel_event=ev, progress_state=ps)
            ),
            queue_label=f"Superpose ({n} structures)",
        )

    def on_superpose_structures_finished(self, payload) -> None:
        self._finish_tool_progress("Superpose")
        from ...conformers.conformer_column_codec import (
            conformer_mol_blocks_b64_json,
            pack_mols_as_confs_cell,
        )

        data = payload if isinstance(payload, dict) else {}
        results = list(data.get("results") or [])
        try:
            ref_oid = int(data.get("ref_oid"))
        except (TypeError, ValueError):
            ref_oid = int(results[0][0]) if results else -1
        geometry = str(data.get("geometry") or "3d")
        self.table.setSortingEnabled(False)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        ok_n = 0
        viewer_mols: list[Chem.Mol] = []
        superpose_col = "superpose"
        try:
            superpose_col = self._next_packed_ensemble_column("superpose", _result_oids(results))
            for _oid, mol, meta in results:
                if mol is None or not (meta or {}).get("ok"):
                    continue
                viewer_mols.append(mol)
                ok_n += 1
            if viewer_mols and ref_oid >= 0:
                ensemble_meta = {
                    "ok": True,
                    "op": "superpose_structures",
                    "geometry": geometry,
                    "n_kept": len(viewer_mols),
                    "n_packed": len(viewer_mols),
                    "n_conf": len(viewer_mols),
                    "ref_oid": int(ref_oid),
                }
                cell = pack_mols_as_confs_cell(ensemble_meta, viewer_mols)
                self._write_packed_ensemble_cells(superpose_col, [(int(ref_oid), cell)])
            self.schedule_calculate_global_bounds()
            self.table.setSortingEnabled(False)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        if viewer_mols and ref_oid >= 0:
            import base64
            import json

            blocks: list[str] = []
            for m in viewer_mols:
                try:
                    block = Chem.MolToMolBlock(m)
                    blocks.append(base64.b64encode(block.encode("utf-8")).decode("ascii"))
                except Exception:
                    continue
            skip_strain = str(geometry).lower().startswith("2")
            strain = None if skip_strain else getattr(self, "_pending_strain_params", None)
            if len(blocks) >= 2:
                payload_b64 = base64.b64encode(json.dumps(blocks).encode("utf-8")).decode("ascii")
                self._open_conformer_results_viewer(
                    payload_b64,
                    title="Superpose",
                    confs_column=superpose_col,
                    oid=int(ref_oid),
                    initial_superpose=True,
                    mols=viewer_mols,
                    strain_params=strain,
                )
            elif len(blocks) == 1:
                payload_b64 = conformer_mol_blocks_b64_json(viewer_mols[0])
                self._open_conformer_results_viewer(
                    payload_b64,
                    title="Superpose",
                    confs_column=superpose_col,
                    oid=int(ref_oid),
                    initial_superpose=False,
                    mols=viewer_mols[:1],
                    strain_params=strain,
                )
        failed = len(results) - ok_n
        status = f"Superpose: packed {ok_n} onto reference OID {ref_oid}"
        if failed:
            status += f" ({failed} failed)"
        if superpose_col != "superpose":
            status += f"; wrote overlays to “{superpose_col}”"
        self.status_label.setText(status + ".")

    def _open_conformer_results_viewer(
        self,
        blocks_b64: str,
        *,
        title: str,
        confs_column: str,
        oid: int | None,
        initial_superpose: bool = False,
        mol: Chem.Mol | None = None,
        mols: list[Chem.Mol] | None = None,
        strain_params: object | None = None,
    ) -> None:
        from ...workers import (
            StrainEnergyParams,
            strain_overlay_for_blocks_b64,
            strain_overlay_for_mol,
            strain_overlay_for_mols,
        )
        from ..mol_viewer_3d import open_conformation_viewer_from_blocks_payload

        params = strain_params if strain_params is not None else StrainEnergyParams()
        overlay = None
        try:
            if mols:
                overlay = strain_overlay_for_mols(mols, params)
            elif mol is not None:
                overlay = strain_overlay_for_mol(mol, params)
            else:
                overlay = strain_overlay_for_blocks_b64(blocks_b64, params)
        except Exception:
            logger.debug("strain overlay failed", exc_info=True)
        ref_idx = 0
        if overlay:
            try:
                ref_idx = int(overlay.get("ref_idx", params.reference_conformer_index) or 0)
            except (TypeError, ValueError):
                ref_idx = 0
        open_conformation_viewer_from_blocks_payload(
            self,
            blocks_b64,
            title=title,
            initial_superpose=initial_superpose,
            strain_overlay=overlay,
            initial_conf_index=ref_idx,
            export_parent_oid=oid,
            export_confs_column=confs_column,
            source_oid=oid,
        )

    def open_packed_conformer_viewer(
        self,
        blocks_json_b64: str,
        *,
        title: str = "View Conformers",
        export_parent_oid: int | None = None,
        export_confs_column: str = "confs",
        source_oid: int | None = None,
        initial_superpose: bool = False,
    ) -> None:
        oid = source_oid if source_oid is not None else export_parent_oid
        self._open_conformer_results_viewer(
            blocks_json_b64,
            title=title,
            confs_column=export_confs_column,
            oid=oid,
            initial_superpose=initial_superpose,
        )

    def _auto_open_first_conformer_results(
        self,
        results: list,
        *,
        title: str,
        confs_column: str,
        initial_superpose: bool,
    ) -> int:
        from ...conformers.conformer_column_codec import (
            conformer_mol_blocks_b64_json,
            unpack_confs_blocks_json_b64,
        )

        n_ok = 0
        opened = False
        for item in results:
            if len(item) < 2:
                continue
            oid, mol = int(item[0]), item[1]
            payload = item[2] if len(item) > 2 else None
            b64 = unpack_confs_blocks_json_b64(payload) if isinstance(payload, str) else None
            if not b64 and mol is not None:
                try:
                    if mol.GetNumConformers() >= 1:
                        b64 = conformer_mol_blocks_b64_json(mol)
                except Exception:
                    b64 = None
            if not b64:
                continue
            n_ok += 1
            if opened:
                continue
            self._open_conformer_results_viewer(
                b64,
                title=title,
                confs_column=confs_column,
                oid=oid,
                initial_superpose=initial_superpose,
                mol=mol if isinstance(mol, Chem.Mol) else None,
                strain_params=getattr(self, "_pending_strain_params", None),
            )
            opened = True
        return n_ok

    def _next_packed_ensemble_column(self, base: str, result_oids: list[int] | None = None) -> str:
        """Return a packed-ensemble header, inserting it when it is not already in the table."""
        from .conformer_writeback import next_packed_ensemble_column

        return next_packed_ensemble_column(self, base, result_oids)

    def _write_packed_ensemble_cells(self, column: str, pairs: list[tuple[int, str]]) -> None:
        """Store packed ensembles under *column*, demoting payloads into the sidecar keyed by that header."""
        from .conformer_writeback import write_packed_ensemble_cells

        return write_packed_ensemble_cells(self, column, pairs)

    def _write_ensemble_worker_results(self, column: str, results: list) -> None:
        """Write ``(oid, mol, meta)`` worker results into *column* without packed-cell strings."""
        from .conformer_writeback import write_ensemble_worker_results

        return write_ensemble_worker_results(self, column, results)
