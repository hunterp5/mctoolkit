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

"""Strain-energy workers for packed conformer ensembles."""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit.Chem import AllChem

from ..platform_support.config import load_config
from ..conformers.conformer_column_codec import mol_from_packed_confs_cell
from ..storage import ensemble_mol_for
from .chemistry_worker_common import emit_tool_progress_throttled, normalize_force_field
from .signals import WorkerSignals, emit_partial_results_if_cancelled
from .superpose import RmsdParams, run_conformer_rmsd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrainEnergyParams:
    """Options for :func:`run_strain_energy` / :class:`StrainEnergyWorker`."""

    reference_conformer_index: int = 0
    force_field: str = "MMFF"
    source_column: str = "confs"


STRAIN_ENERGY_HEADERS = ("Strain_energies", "Strain_max", "E_ref")
STRAIN_ALT_FORCE_FIELDS = ("MMFF", "MMFF94s", "UFF")
# kcal/(mol·K); used for Boltzmann populations at 298.15 K
_GAS_CONSTANT_KCAL = 0.00198720425864083
_BOLTZMANN_T_K = 298.15


def _boltzmann_fractions(delta_min_kcal: list[float], t_k: float = _BOLTZMANN_T_K) -> list[float]:
    """Relative populations from ΔE vs the lowest-energy conformer (kcal/mol)."""
    n = len(delta_min_kcal)
    if n == 0:
        return []
    rt = _GAS_CONSTANT_KCAL * float(t_k)
    if rt <= 0:
        rt = _GAS_CONSTANT_KCAL * _BOLTZMANN_T_K
    weights: list[float] = []
    for d in delta_min_kcal:
        clipped = min(max(float(d), 0.0), 80.0)
        weights.append(math.exp(-clipped / rt))
    z = sum(weights)
    if z <= 0:
        return [1.0 / n] * n
    return [w / z for w in weights]


def _single_point_conformer_energies(
    mol: Chem.Mol,
    force_field: str,
    *,
    allow_uff_fallback: bool = True,
) -> tuple[list[float], str] | None:
    """
    Single-point MMFF94, MMFF94s, or UFF energies (kcal/mol) — no minimization.

    Adds hydrogens with coordinates when needed for the force field.
    """
    try:
        m = Chem.AddHs(Chem.Mol(mol), addCoords=True)
    except Exception:
        return None
    try:
        cids = sorted(int(c.GetId()) for c in m.GetConformers())
    except Exception:
        cids = list(range(int(m.GetNumConformers())))
    if not cids:
        return None
    ff_choice = normalize_force_field(force_field)
    energies: list[float] = []
    if ff_choice in {"MMFF", "MMFF94s"}:
        variant = "MMFF94s" if ff_choice == "MMFF94s" else "MMFF94"
        try:
            mp = AllChem.MMFFGetMoleculeProperties(m, mmffVariant=variant)
        except Exception:
            mp = None
        if mp is not None:
            for cid in cids:
                try:
                    ff = AllChem.MMFFGetMoleculeForceField(m, mp, confId=int(cid))
                    if ff is None:
                        return None
                    energies.append(float(ff.CalcEnergy()))
                except Exception:
                    return None
            return energies, ff_choice
        if not allow_uff_fallback:
            return None
    for cid in cids:
        try:
            ff = AllChem.UFFGetMoleculeForceField(m, confId=int(cid))
            if ff is None:
                return None
            energies.append(float(ff.CalcEnergy()))
        except Exception:
            return None
    return energies, "UFF"


def single_point_energy_kcal(mol: Chem.Mol, force_field: str) -> float | None:
    """Vacuum single-point energy (kcal/mol) of the first conformer; no minimization."""
    if mol is None:
        return None
    got = _single_point_conformer_energies(mol, force_field, allow_uff_fallback=False)
    if got is None or not got[0]:
        return None
    value = float(got[0][0])
    if not math.isfinite(value):
        return None
    return value


def _alternate_force_field_energies(
    mol: Chem.Mol, primary_ff: str, n_conf: int
) -> dict[str, list[float]]:
    """Single-point energies for the other built-in force fields, when they apply."""
    out: dict[str, list[float]] = {}
    for alt in STRAIN_ALT_FORCE_FIELDS:
        if alt == primary_ff:
            continue
        got = _single_point_conformer_energies(mol, alt, allow_uff_fallback=False)
        if got is None:
            continue
        alt_e, alt_name = got
        if len(alt_e) != n_conf:
            continue
        out[alt_name] = [round(float(e), 4) for e in alt_e]
    return out


def run_strain_energy(
    mol: Chem.Mol,
    params: StrainEnergyParams,
    cancel_event: threading.Event | None = None,
) -> tuple[dict[str, str] | None, dict]:
    """
    Compute strain energy of each conformer relative to a reference conformer.

    Strain_i = E_i − E_ref (kcal/mol) from a single-point force-field evaluation
    (coordinates are not re-minimized). Also reports ΔE vs the lowest-energy
    conformer and Boltzmann populations at 298.15 K.
    """
    meta: dict = {"ok": False, "op": "strain"}
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta
    if mol is None or mol.GetNumAtoms() == 0:
        meta["err"] = "empty_molecule"
        return None, meta
    try:
        nconf = int(mol.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf < 1:
        meta["err"] = "no_conformers"
        return None, meta

    opt = _single_point_conformer_energies(mol, params.force_field)
    if opt is None:
        meta["err"] = "energy_failed"
        return None, meta
    energies, ff = opt
    meta["ff"] = ff
    meta["n_conf"] = len(energies)
    ref_idx = int(params.reference_conformer_index)
    if ref_idx < 0:
        ref_idx = 0
    ref_clamped = False
    if ref_idx >= len(energies):
        ref_idx = len(energies) - 1
        ref_clamped = True
    e_ref = float(energies[ref_idx])
    e_min = min(float(e) for e in energies)
    strains = [float(e) - e_ref for e in energies]
    deltas_min = [float(e) - e_min for e in energies]
    pop_fracs = _boltzmann_fractions(deltas_min)
    meta["ok"] = True
    meta["ref_idx"] = ref_idx
    meta["ref_clamped"] = ref_clamped
    meta["e_ref_kcal"] = round(e_ref, 4)
    meta["e_min_kcal"] = round(e_min, 4)
    meta["strain_max_kcal"] = round(max(strains), 4) if strains else 0.0
    meta["energies"] = [round(float(e), 4) for e in energies]
    meta["strains"] = [round(float(s), 4) for s in strains]
    meta["deltas_min"] = [round(float(s), 4) for s in deltas_min]
    meta["pop_fracs"] = [round(float(p), 6) for p in pop_fracs]
    by_ff = {ff: list(meta["energies"])}
    by_ff.update(_alternate_force_field_energies(mol, ff, len(energies)))
    meta["energies_by_ff"] = by_ff
    row = {
        "Strain_energies": ";".join(f"{s:.4f}" for s in strains),
        "Strain_max": f"{max(strains):.4f}" if strains else "0.0000",
        "E_ref": f"{e_ref:.4f}",
    }
    return row, meta


def _rmsd_overlay_fields(mol: Chem.Mol, ref_idx: int) -> tuple[list[float], float]:
    """RMSD of each conformer vs *ref_idx* after rigid alignment, or empty on failure."""
    _rms_row, rms_meta = run_conformer_rmsd(
        mol,
        RmsdParams(reference_conformer_index=int(ref_idx), heavy_atoms_only=True),
    )
    rms_vals: list[float] = []
    rms_max = 0.0
    if rms_meta.get("ok") and _rms_row:
        try:
            rms_vals = [
                float(x) for x in str(_rms_row.get("RMSD_values", "")).split(";") if x.strip()
            ]
        except Exception:
            rms_vals = []
        try:
            rms_max = float(rms_meta.get("rms_max", _rms_row.get("RMSD_max", 0.0)))
        except Exception:
            rms_max = max(rms_vals) if rms_vals else 0.0
        if len(rms_vals) != int(mol.GetNumConformers()):
            rms_vals = []
    return rms_vals, rms_max


def _overlay_dict_from_strain_meta(
    meta: dict,
    *,
    rmsds: list[float] | None = None,
    rmsd_max: float = 0.0,
) -> dict | None:
    if not meta.get("ok"):
        return None
    energies = meta.get("energies") or []
    strains = meta.get("strains") or []
    if not energies or len(strains) != len(energies):
        return None
    overlay = {
        "energies": [float(e) for e in energies],
        "deltas": [float(s) for s in strains],
        "deltas_min": [float(s) for s in (meta.get("deltas_min") or [])],
        "pop_fracs": [float(p) for p in (meta.get("pop_fracs") or [])],
        "e_ref": float(meta.get("e_ref_kcal", 0.0)),
        "e_min": float(meta.get("e_min_kcal", 0.0)),
        "strain_max": float(meta.get("strain_max_kcal", 0.0)),
        "ref_idx": int(meta.get("ref_idx", 0)),
        "ff": str(meta.get("ff") or ""),
        "energies_by_ff": dict(meta.get("energies_by_ff") or {}),
    }
    if rmsds and len(rmsds) == len(energies):
        overlay["rmsds"] = [float(x) for x in rmsds]
        overlay["rmsd_max"] = float(rmsd_max)
    return overlay


def _try_merge_mols_as_conformers(mols: list[Chem.Mol]) -> Chem.Mol | None:
    """Merge same-atom-count mols into one multi-conformer mol, or None."""
    if not mols:
        return None
    try:
        base = Chem.Mol(mols[0])
    except Exception:
        return None
    if base.GetNumConformers() < 1:
        return None
    if len(mols) == 1:
        return base
    na = int(base.GetNumAtoms())
    for extra in mols[1:]:
        if extra is None or extra.GetNumAtoms() != na or extra.GetNumConformers() < 1:
            return None
        try:
            base.AddConformer(extra.GetConformer(0), assignId=True)
        except Exception:
            return None
    return base


def _mols_from_blocks_b64(blocks_json_b64: str) -> list[Chem.Mol]:
    raw = (blocks_json_b64 or "").strip()
    if not raw:
        return []
    try:
        encs = json.loads(base64.b64decode(raw.encode("ascii")))
    except Exception:
        return []
    if not isinstance(encs, list):
        return []
    mols: list[Chem.Mol] = []
    for enc in encs:
        if not isinstance(enc, str):
            continue
        try:
            block = base64.b64decode(enc.encode("ascii")).decode("utf-8")
        except Exception:
            continue
        m = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
        if m is None:
            m = Chem.MolFromMolBlock(block, sanitize=False, removeHs=False)
        if m is not None and m.GetNumConformers() >= 1:
            mols.append(m)
    return mols


def strain_overlay_for_mol(
    mol: Chem.Mol,
    params: StrainEnergyParams | None = None,
) -> dict | None:
    """Build the 3D-viewer energy table payload for a multi-conformer molecule."""
    if mol is None or mol.GetNumConformers() < 1:
        return None
    p = params or StrainEnergyParams()
    _row, meta = run_strain_energy(mol, p)
    overlay = _overlay_dict_from_strain_meta(meta)
    if overlay is None:
        return None
    rms_vals, rms_max = _rmsd_overlay_fields(mol, int(meta.get("ref_idx", 0)))
    if rms_vals:
        overlay["rmsds"] = rms_vals
        overlay["rmsd_max"] = float(rms_max)
    return overlay


def strain_overlay_for_mols(
    mols: list[Chem.Mol],
    params: StrainEnergyParams | None = None,
) -> dict | None:
    """Score one mol or a list of poses (e.g. superposed structures)."""
    if not mols:
        return None
    merged = _try_merge_mols_as_conformers(mols)
    if merged is not None:
        return strain_overlay_for_mol(merged, params)
    p = params or StrainEnergyParams()
    energies: list[float] = []
    ff_used = normalize_force_field(p.force_field)
    for m in mols:
        opt = _single_point_conformer_energies(m, p.force_field)
        if opt is None or not opt[0]:
            return None
        energies.append(float(opt[0][0]))
        ff_used = str(opt[1] or ff_used)
    ref_idx = int(p.reference_conformer_index or 0)
    if ref_idx < 0:
        ref_idx = 0
    if ref_idx >= len(energies):
        ref_idx = len(energies) - 1
    e_ref = float(energies[ref_idx])
    e_min = min(energies)
    strains = [float(e) - e_ref for e in energies]
    deltas_min = [float(e) - e_min for e in energies]
    meta = {
        "ok": True,
        "ff": ff_used,
        "ref_idx": ref_idx,
        "e_ref_kcal": round(e_ref, 4),
        "e_min_kcal": round(e_min, 4),
        "strain_max_kcal": round(max(strains), 4) if strains else 0.0,
        "energies": [round(float(e), 4) for e in energies],
        "strains": [round(float(s), 4) for s in strains],
        "deltas_min": [round(float(s), 4) for s in deltas_min],
        "pop_fracs": [round(float(x), 6) for x in _boltzmann_fractions(deltas_min)],
        "energies_by_ff": {ff_used: [round(float(e), 4) for e in energies]},
    }
    return _overlay_dict_from_strain_meta(meta)


def strain_overlay_for_blocks_b64(
    blocks_json_b64: str,
    params: StrainEnergyParams | None = None,
) -> dict | None:
    """Score packed 3Dmol blocks (same-molecule conformers or distinct structures)."""
    mols = _mols_from_blocks_b64(blocks_json_b64)
    if not mols:
        return None
    return strain_overlay_for_mols(mols, params)


def _strain_energy_row_task(task: tuple) -> tuple[int, dict[str, str]]:
    oid, src, params = task[0], task[1], task[2]
    cancel_event = task[3] if len(task) > 3 else None
    db_path = task[4] if len(task) > 4 else None
    na = {h: "N/A" for h in STRAIN_ENERGY_HEADERS}
    try:
        if cancel_event is not None and cancel_event.is_set():
            return oid, na
        mol = None
        if db_path and not str(src or "").lstrip().startswith("{"):
            mol = ensemble_mol_for(db_path, oid, str(src or ""), min_conformers=1)
        if mol is None:
            mol = mol_from_packed_confs_cell(src or "", min_conformers=1)
        if mol is None:
            return oid, na
        row, meta = run_strain_energy(mol, params, cancel_event=cancel_event)
        if row is None or not meta.get("ok"):
            return oid, na
        return oid, {h: str(row.get(h, "N/A")) for h in STRAIN_ENERGY_HEADERS}
    except Exception:
        logger.exception("StrainEnergyWorker failed for oid=%s", oid)
        return oid, na


class StrainEnergyWorker(QRunnable):
    """Score packed conformer cells; emit descriptor-style columns via ``calculated``."""

    def __init__(
        self,
        data: list[tuple[int, str]],
        params: StrainEnergyParams,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
        output_headers: list[str] | None = None,
        ensemble_db: str | None = None,
    ):
        super().__init__()
        self.data = data
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.ensemble_db = ensemble_db
        if output_headers and len(output_headers) == len(STRAIN_ENERGY_HEADERS):
            self.output_headers = list(output_headers)
        else:
            self.output_headers = list(STRAIN_ENERGY_HEADERS)

    def run(self):
        nrows = len(self.data)
        tot = max(nrows, 1)
        tasks = [(oid, cell, self.params) for oid, cell in self.data]
        cfg = load_config()
        if cfg.conformer_threads is not None:
            max_workers = cfg.conformer_threads
        else:
            max_workers = min(4, max(1, (os.cpu_count() or 4) // 2))
        use_parallel = nrows >= 6 and max_workers > 1
        cancel_ev = self.cancel_event
        results: list = []
        cancelled = False
        done_count = 0
        prog_state = [0, 0.0]
        headers = list(self.output_headers)
        rename = dict(zip(STRAIN_ENERGY_HEADERS, headers))
        try:
            if use_parallel:
                emit_tool_progress_throttled(
                    self.signals,
                    "Calculate strain energy…",
                    0,
                    tot,
                    prog_state,
                    progress_state=self.progress_state,
                )
                ex = ThreadPoolExecutor(max_workers=max_workers)
                shutdown_cancel = False
                try:
                    row_tasks = [(*t, cancel_ev, self.ensemble_db) for t in tasks]
                    pending = {ex.submit(_strain_energy_row_task, rt) for rt in row_tasks}
                    while pending:
                        if cancel_ev is not None and cancel_ev.is_set():
                            shutdown_cancel = True
                            cancelled = True
                            for f in list(pending):
                                if f.done() and not f.cancelled():
                                    try:
                                        results.append(f.result())
                                        done_count += 1
                                    except Exception:
                                        logger.exception("Strain energy row task failed")
                                else:
                                    f.cancel()
                            break
                        completed, pending = wait(
                            pending, timeout=0.08, return_when=FIRST_COMPLETED
                        )
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                results.append(f.result())
                                done_count += 1
                            except Exception:
                                logger.exception("Strain energy row task failed")
                            emit_tool_progress_throttled(
                                self.signals,
                                "Calculate strain energy…",
                                done_count,
                                tot,
                                prog_state,
                                progress_state=self.progress_state,
                            )
                finally:
                    try:
                        ex.shutdown(wait=not shutdown_cancel, cancel_futures=shutdown_cancel)
                    except TypeError:
                        ex.shutdown(wait=not shutdown_cancel)
                emit_tool_progress_throttled(
                    self.signals,
                    "Calculate strain energy…",
                    min(done_count, tot),
                    tot,
                    prog_state,
                    progress_state=self.progress_state,
                )
            else:
                for done, t in enumerate(tasks, start=1):
                    if cancel_ev is not None and cancel_ev.is_set():
                        cancelled = True
                        break
                    results.append(_strain_energy_row_task((*t, cancel_ev, self.ensemble_db)))
                    done_count = done
                    emit_tool_progress_throttled(
                        self.signals,
                        "Calculate strain energy…",
                        done,
                        tot,
                        prog_state,
                        progress_state=self.progress_state,
                    )
        except Exception:
            logger.exception("StrainEnergyWorker failed")
        finally:
            emit_partial_results_if_cancelled(
                self.signals, "Calculate strain energy", done_count, tot, cancelled
            )
            mapped: list[tuple[int, dict[str, str]]] = []
            for oid, row in results:
                mapped.append((int(oid), {rename.get(k, k): v for k, v in row.items()}))
            try:
                self.signals.calculated.emit(mapped, headers)
            except Exception:
                logger.warning("strain energy calculated emit failed", exc_info=True)
