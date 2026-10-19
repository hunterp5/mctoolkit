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

"""Stochastic ETKDG conformer generation workers."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit.Chem import AllChem

from ..chem.molecule_conversion import mol_from_tool_input
from ..platform_support.config import load_config
from .chemistry_worker_common import (
    emit_tool_progress_throttled,
    is_gaff_force_field,
    mmff_variant,
    normalize_force_field,
)
from .signals import WorkerSignals, emit_partial_results_if_cancelled
from .superpose import SuperposeParams, run_superpose_conformers

logger = logging.getLogger(__name__)

_PROGRESS_LABEL = "Generate conformations…"


def generation_progress_label(done: int, tot: int) -> str:
    """Status text; call out the last in-flight molecule so n-1/n does not look stuck."""
    if int(tot) > 1 and 0 < int(done) < int(tot) and (int(tot) - int(done)) == 1:
        return f"{_PROGRESS_LABEL} last molecule"
    return _PROGRESS_LABEL


def drain_completed_futures(futures, results: list) -> tuple[set, int]:
    """Move finished (non-cancelled) futures into *results*; return leftover futures and added count."""
    remaining = set()
    added = 0
    for fut in futures:
        if not fut.done():
            remaining.add(fut)
            continue
        if fut.cancelled():
            continue
        try:
            results.append(fut.result())
            added += 1
        except Exception:
            logger.exception("Conformer row task failed")
    return remaining, added


CONFORMER_FORCE_FIELDS: tuple[str, ...] = ("MMFF", "MMFF94s", "UFF", "GAFF2", "GAFF")
DEFAULT_CONFORMER_FORCE_FIELD = "MMFF94s"


@dataclass(frozen=True)
class ConformerGenParams:
    """Options for :func:`run_conformer_generation` / :class:`ConformerGenerationWorker`."""

    num_confs: int = 10
    energy_window_kcal: float = 10.0
    force_field: str = DEFAULT_CONFORMER_FORCE_FIELD
    random_seed: int = 0xC0FFEE
    prune_rms_threshold: float = -1.0
    max_iterations: int = 200
    # When non-empty, generated conformers are rigidly aligned on this substructure.
    align_pattern: str = ""
    align_pattern_is_smarts: bool = False
    # 0 = skip post-minimization RMS pruning.
    post_min_rms_threshold: float = 0.0
    # 0 = keep every conformer that passed the energy window / RMS prune.
    max_keep: int = 0
    enforce_chirality: bool = True
    use_random_coords: bool = False
    use_exp_torsion_prefs: bool = True
    use_small_ring_torsions: bool = True
    use_macrocycle_torsions: bool = True
    use_basic_knowledge: bool = True
    only_heavy_atoms_for_rms: bool = True
    # 0 = leave the ETKDG maxIterations default (typically 10 × n_atoms).
    max_embed_attempts: int = 0
    keep_hydrogens: bool = False

    @classmethod
    def single_lowest_energy(
        cls,
        *,
        force_field: str = DEFAULT_CONFORMER_FORCE_FIELD,
        random_seed: int = 0xC0FFEE,
        prune_rms_threshold: float = -1.0,
        max_iterations: int = 200,
        enforce_chirality: bool = True,
        use_random_coords: bool = False,
        use_exp_torsion_prefs: bool = True,
        use_small_ring_torsions: bool = True,
        use_macrocycle_torsions: bool = True,
        use_basic_knowledge: bool = True,
        only_heavy_atoms_for_rms: bool = True,
        max_embed_attempts: int = 0,
        keep_hydrogens: bool = False,
    ) -> "ConformerGenParams":
        """One embedded conformer, minimized; written to the ``confs`` column."""
        return cls(
            num_confs=1,
            energy_window_kcal=0.0,
            force_field=force_field,
            random_seed=random_seed,
            prune_rms_threshold=prune_rms_threshold,
            max_iterations=max_iterations,
            enforce_chirality=enforce_chirality,
            use_random_coords=use_random_coords,
            use_exp_torsion_prefs=use_exp_torsion_prefs,
            use_small_ring_torsions=use_small_ring_torsions,
            use_macrocycle_torsions=use_macrocycle_torsions,
            use_basic_knowledge=use_basic_knowledge,
            only_heavy_atoms_for_rms=only_heavy_atoms_for_rms,
            max_embed_attempts=max_embed_attempts,
            keep_hydrogens=keep_hydrogens,
        )


def _set_embed_attr(params_obj, name: str, value) -> None:
    if not hasattr(params_obj, name):
        return
    try:
        setattr(params_obj, name, value)
    except Exception:
        pass


def _etkdg_params(params: ConformerGenParams):
    for name in ("ETKDGv3", "ETKDGv2", "ETKDG"):
        factory = getattr(AllChem, name, None)
        if factory is None:
            continue
        try:
            p = factory()
            p.randomSeed = int(params.random_seed)
            if params.prune_rms_threshold is not None and params.prune_rms_threshold >= 0:
                p.pruneRmsThresh = float(params.prune_rms_threshold)
            _set_embed_attr(p, "enforceChirality", bool(params.enforce_chirality))
            _set_embed_attr(p, "useRandomCoords", bool(params.use_random_coords))
            _set_embed_attr(p, "useExpTorsionAnglePrefs", bool(params.use_exp_torsion_prefs))
            _set_embed_attr(p, "useBasicKnowledge", bool(params.use_basic_knowledge))
            _set_embed_attr(p, "useSmallRingTorsions", bool(params.use_small_ring_torsions))
            _set_embed_attr(p, "useMacrocycleTorsions", bool(params.use_macrocycle_torsions))
            _set_embed_attr(p, "onlyHeavyAtomsForRMS", bool(params.only_heavy_atoms_for_rms))
            if int(params.max_embed_attempts) > 0:
                _set_embed_attr(p, "maxIterations", int(params.max_embed_attempts))
            return p
        except Exception:
            continue
    return None


def _heavy_atom_ids(mol: Chem.Mol) -> list[int]:
    return [i for i in range(mol.GetNumAtoms()) if mol.GetAtomWithIdx(i).GetAtomicNum() != 1]


def _conformer_ids(mol: Chem.Mol) -> list[int]:
    try:
        return [int(c.GetId()) for c in mol.GetConformers()]
    except Exception:
        return list(range(int(mol.GetNumConformers())))


def _drop_conformers(mol: Chem.Mol, drop: set[int]) -> None:
    for cid in sorted(drop, reverse=True):
        try:
            mol.RemoveConformer(int(cid))
        except Exception:
            pass


def _prune_conformers_by_rms(
    mol: Chem.Mol,
    energies_by_cid: dict[int, float],
    thresh: float,
    *,
    heavy_atoms_only: bool,
    cancel_event: threading.Event | None = None,
) -> dict[int, float]:
    """Keep lowest-energy conformers that are at least *thresh* Å RMS from each other."""
    if thresh <= 0 or len(energies_by_cid) < 2:
        return energies_by_cid
    atom_ids = _heavy_atom_ids(mol) if heavy_atoms_only else []
    if heavy_atoms_only and len(atom_ids) < 2:
        atom_ids = []
    ranked = sorted(energies_by_cid, key=lambda cid: (energies_by_cid[cid], cid))
    kept: list[int] = []
    for cid in ranked:
        if cancel_event is not None and cancel_event.is_set():
            break
        too_close = False
        for kept_cid in kept:
            try:
                if atom_ids:
                    rms = float(
                        AllChem.GetConformerRMS(
                            mol, int(cid), int(kept_cid), atomIds=atom_ids, prealigned=False
                        )
                    )
                else:
                    rms = float(
                        AllChem.GetConformerRMS(mol, int(cid), int(kept_cid), prealigned=False)
                    )
            except Exception:
                rms = thresh + 1.0
            if rms < thresh:
                too_close = True
                break
        if not too_close:
            kept.append(cid)
    drop = set(energies_by_cid) - set(kept)
    _drop_conformers(mol, drop)
    return {cid: energies_by_cid[cid] for cid in kept}


def _keep_lowest_energy(
    mol: Chem.Mol, energies_by_cid: dict[int, float], max_keep: int
) -> dict[int, float]:
    if max_keep <= 0 or len(energies_by_cid) <= max_keep:
        return energies_by_cid
    ranked = sorted(energies_by_cid, key=lambda cid: (energies_by_cid[cid], cid))
    keep = set(ranked[: int(max_keep)])
    _drop_conformers(mol, set(energies_by_cid) - keep)
    return {cid: energies_by_cid[cid] for cid in keep}


def _gaff_minimize_error(exc: BaseException) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    if len(msg) > 400:
        msg = msg[:397] + "..."
    if msg.lower() in {"cancelled"}:
        return "cancelled"
    if msg.lower().startswith("gaff") or "ambertools" in msg.lower():
        return msg
    return f"gaff:{msg}"


def _optimize_conformer_energies_gaff(
    m: Chem.Mol,
    params: ConformerGenParams,
    meta: dict,
    max_it: int,
    cancel_event: threading.Event | None = None,
) -> tuple[list[float], str] | None:
    from .conformer_gaff import optimize_conformer_energies_gaff

    try:
        return optimize_conformer_energies_gaff(
            m, params.force_field, max_it, cancel_event=cancel_event
        )
    except Exception as e:
        meta["err"] = _gaff_minimize_error(e)
        return None


def _optimize_conformer_energies_cooperative(
    m: Chem.Mol,
    params: ConformerGenParams,
    meta: dict,
    cancel_event: threading.Event,
    max_it: int,
) -> tuple[list[float], str] | None:
    """Per-conformer minimization so ``cancel_event`` can abort between conformers."""
    ff_choice = normalize_force_field(params.force_field)
    if is_gaff_force_field(ff_choice):
        return _optimize_conformer_energies_gaff(m, params, meta, max_it, cancel_event=cancel_event)
    cids = _conformer_ids(m)
    energies: list[float] = []
    if ff_choice in {"MMFF", "MMFF94s"}:
        variant = mmff_variant(ff_choice)
        try:
            mp = AllChem.MMFFGetMoleculeProperties(m, mmffVariant=variant)
        except TypeError:
            mp = AllChem.MMFFGetMoleculeProperties(m)
        if mp is not None:
            for cid in cids:
                if cancel_event.is_set():
                    meta["err"] = "cancelled"
                    return None
                try:
                    code = AllChem.MMFFOptimizeMolecule(
                        m, confId=int(cid), maxIters=max_it, mmffVariant=variant
                    )
                except TypeError:
                    code = AllChem.MMFFOptimizeMolecule(m, confId=int(cid), maxIters=max_it)
                if code == -1:
                    meta["err"] = "mmff_opt"
                    return None
                ff = AllChem.MMFFGetMoleculeForceField(m, mp, confId=int(cid))
                if ff is None:
                    meta["err"] = "mmff_ff"
                    return None
                energies.append(float(ff.CalcEnergy()))
            return energies, ff_choice
    for cid in cids:
        if cancel_event.is_set():
            meta["err"] = "cancelled"
            return None
        code = AllChem.UFFOptimizeMolecule(m, confId=int(cid), maxIters=max_it)
        if code == -1:
            meta["err"] = "uff_opt"
            return None
        ff = AllChem.UFFGetMoleculeForceField(m, confId=int(cid))
        energies.append(float(ff.CalcEnergy()))
    return energies, "UFF"


def _optimize_conformer_energies_batch(
    m: Chem.Mol, params: ConformerGenParams, meta: dict, max_it: int
) -> tuple[list[float], str] | None:
    """Fast path: RDKit batch optimizers (no cooperative cancel during minimization)."""
    ff = normalize_force_field(params.force_field)
    if is_gaff_force_field(ff):
        return _optimize_conformer_energies_gaff(m, params, meta, max_it)
    res = None
    try:
        if ff in {"MMFF", "MMFF94s"}:
            variant = mmff_variant(ff)
            try:
                mp = AllChem.MMFFGetMoleculeProperties(m, mmffVariant=variant)
            except TypeError:
                mp = AllChem.MMFFGetMoleculeProperties(m)
            if mp is None:
                ff = "UFF"
            else:
                try:
                    res = AllChem.MMFFOptimizeMoleculeConfs(
                        m, numThreads=1, maxIters=max_it, mmffVariant=variant
                    )
                except TypeError:
                    res = AllChem.MMFFOptimizeMoleculeConfs(m, numThreads=1, maxIters=max_it)
        if ff == "UFF" or res is None:
            res = AllChem.UFFOptimizeMoleculeConfs(m, maxIters=max_it)
            ff = "UFF"
    except Exception as e:
        meta["err"] = f"minimize:{e.__class__.__name__}"
        return None
    return [float(t[1]) for t in res], ff


def run_conformer_generation(
    mol: Chem.Mol,
    params: ConformerGenParams,
    cancel_event: threading.Event | None = None,
) -> tuple[Chem.Mol | None, dict]:
    """
    Embed multiple conformers, minimize (MMFF, MMFF94s, UFF, GAFF, or GAFF2), prune by energy window
    (and optional post-minimize RMS / max-keep), then RemoveHs unless ``keep_hydrogens``.

    When ``params.align_pattern`` is set and at least two conformers remain, they are
    rigidly aligned on that substructure (same matching rules as Superpose).

    Returns ``(mol_or_None, meta)``. The UI writes coordinates to the disk-backed ensemble
    store and a short metadata cell in the ``confs`` column. It does **not** replace the
    row's working molecule or redraw the Structure column.

    When ``cancel_event`` is set, minimization checks it between conformers (slower than the batch
    optimizers used when ``cancel_event`` is None). Embed is still a single RDKit call.
    """
    meta: dict = {
        "ok": False,
        "n_requested": int(params.num_confs),
        "seed": int(params.random_seed),
    }
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta
    if mol is None or mol.GetNumAtoms() == 0:
        meta["err"] = "empty_molecule"
        return None, meta

    try:
        m = Chem.AddHs(Chem.Mol(mol), addCoords=True)
    except Exception as e:
        meta["err"] = f"addhs:{e.__class__.__name__}"
        return None, meta

    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta

    embed_params = _etkdg_params(params)
    if embed_params is None:
        meta["err"] = "no_etkdg"
        return None, meta

    try:
        cids = AllChem.EmbedMultipleConfs(m, int(params.num_confs), embed_params)
        n_embed = len(cids) if cids is not None else 0
    except Exception as e:
        meta["err"] = f"embed:{e.__class__.__name__}"
        return None, meta

    meta["n_embedded"] = int(n_embed)
    if n_embed == 0 or m.GetNumConformers() == 0:
        meta["err"] = "no_embedded_confs"
        return None, meta

    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta

    max_it = max(1, int(params.max_iterations))
    if cancel_event is None:
        opt = _optimize_conformer_energies_batch(m, params, meta, max_it)
    else:
        opt = _optimize_conformer_energies_cooperative(m, params, meta, cancel_event, max_it)
    if opt is None:
        return None, meta
    energies, ff = opt
    meta["ff"] = ff
    conf_ids = _conformer_ids(m)
    if len(energies) != len(conf_ids):
        meta["err"] = "energy_count_mismatch"
        return None, meta
    e_by_cid = {int(cid): float(e) for cid, e in zip(conf_ids, energies)}
    emin = min(e_by_cid.values())
    meta["e_min_kcal"] = round(emin, 4)
    window = float(params.energy_window_kcal)
    meta["ewin_kcal"] = round(window, 4) if window > 0 else 0.0
    if window > 0:
        keep_cids = {cid for cid, e in e_by_cid.items() if e <= emin + window}
    else:
        keep_cids = set(e_by_cid)
    _drop_conformers(m, set(e_by_cid) - keep_cids)
    e_by_cid = {cid: e_by_cid[cid] for cid in keep_cids}
    meta["n_after_ewin"] = len(e_by_cid)

    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        return None, meta

    post_rms = float(params.post_min_rms_threshold)
    meta["post_min_rms_A"] = round(post_rms, 4) if post_rms > 0 else 0.0
    if post_rms > 0:
        e_by_cid = _prune_conformers_by_rms(
            m,
            e_by_cid,
            post_rms,
            heavy_atoms_only=bool(params.only_heavy_atoms_for_rms),
            cancel_event=cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            meta["err"] = "cancelled"
            return None, meta
    meta["n_after_rms_prune"] = len(e_by_cid)

    max_keep = int(params.max_keep)
    meta["max_keep"] = int(max_keep) if max_keep > 0 else 0
    if max_keep > 0:
        e_by_cid = _keep_lowest_energy(m, e_by_cid, max_keep)

    kept_energies = list(e_by_cid.values())
    meta["e_max_kept_kcal"] = round(max(kept_energies), 4) if kept_energies else None
    meta["n_kept"] = len(e_by_cid)

    if not params.keep_hydrogens:
        try:
            m = Chem.RemoveHs(m)
        except Exception:
            pass
    else:
        meta["keep_hs"] = True

    aligned, align_err = _align_generated_conformers(m, params, meta, cancel_event)
    if align_err:
        return None, meta
    m = aligned

    meta["ok"] = True
    return m, meta


def _conformer_row_task(task: tuple) -> tuple[int, Chem.Mol | None, dict]:
    oid, mol, params = task[0], task[1], task[2]
    cancel_event = task[3] if len(task) > 3 else None
    try:
        if mol is None:
            meta = {
                "ok": False,
                "err": "missing_mol",
                "n_requested": int(params.num_confs),
                "seed": int(params.random_seed),
            }
            return oid, None, meta
        new_m, meta = run_conformer_generation(mol, params, cancel_event=cancel_event)
        return oid, new_m, dict(meta)
    except Exception as e:
        logger.exception("ConformerGenerationWorker failed for oid=%s", oid)
        meta = {
            "ok": False,
            "err": str(e)[:200],
            "n_requested": int(params.num_confs),
            "seed": int(params.random_seed),
        }
        return oid, None, meta


class ConformerGenerationWorker(QRunnable):
    """Run :func:`run_conformer_generation` off the UI thread (optionally parallel per row)."""

    def __init__(
        self,
        data: list[tuple[int, Chem.Mol | None]],
        params: ConformerGenParams,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.data = data
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self):
        nrows = len(self.data)
        tot = max(nrows, 1)
        tasks = [(oid, mol_from_tool_input(item), self.params) for oid, item in self.data]
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
        try:
            if use_parallel:
                emit_tool_progress_throttled(
                    self.signals,
                    generation_progress_label(0, tot),
                    0,
                    tot,
                    prog_state,
                    progress_state=self.progress_state,
                )
                ex = ThreadPoolExecutor(max_workers=max_workers)
                shutdown_cancel = False
                try:
                    row_tasks = [(*t, cancel_ev) for t in tasks]
                    pending = {ex.submit(_conformer_row_task, rt) for rt in row_tasks}
                    done_count = 0
                    while pending:
                        if cancel_ev is not None and cancel_ev.is_set():
                            shutdown_cancel = True
                            cancelled = True
                            pending, added = drain_completed_futures(pending, results)
                            done_count += added
                            for fut in list(pending):
                                fut.cancel()
                            break
                        completed, pending = wait(
                            pending, timeout=0.08, return_when=FIRST_COMPLETED
                        )
                        pending, added = drain_completed_futures(completed | pending, results)
                        if added:
                            done_count += added
                            emit_tool_progress_throttled(
                                self.signals,
                                generation_progress_label(done_count, tot),
                                done_count,
                                tot,
                                prog_state,
                                progress_state=self.progress_state,
                                force=done_count >= tot,
                            )
                finally:
                    try:
                        ex.shutdown(wait=not shutdown_cancel, cancel_futures=shutdown_cancel)
                    except TypeError:
                        ex.shutdown(wait=not shutdown_cancel)
            else:
                for done, t in enumerate(tasks, start=1):
                    if cancel_ev is not None and cancel_ev.is_set():
                        cancelled = True
                        break
                    results.append(_conformer_row_task((*t, cancel_ev)))
                    done_count = done
                    emit_tool_progress_throttled(
                        self.signals,
                        generation_progress_label(done, tot),
                        done,
                        tot,
                        prog_state,
                        progress_state=self.progress_state,
                        force=done >= tot,
                    )
        finally:
            final_done = tot if not cancelled else min(done_count, tot)
            emit_tool_progress_throttled(
                self.signals,
                _PROGRESS_LABEL,
                final_done,
                tot,
                prog_state,
                progress_state=self.progress_state,
                force=True,
            )
            emit_partial_results_if_cancelled(
                self.signals, "Generate conformations", done_count, tot, cancelled
            )
            try:
                self.signals.conformers_finished.emit(results)
            except Exception:
                logger.warning("conformers_finished emit failed", exc_info=True)


def _align_generated_conformers(
    m: Chem.Mol,
    params: ConformerGenParams,
    meta: dict,
    cancel_event: threading.Event | None,
) -> tuple[Chem.Mol | None, str | None]:
    """
    Rigidly overlay generated conformers on ``params.align_pattern`` when set.

    Returns ``(mol, None)`` on success (including no-op when the pattern is empty
    or only one conformer remains). On failure, writes ``meta["err"]`` and returns
    ``(None, error_code)``.
    """
    ap = (params.align_pattern or "").strip()
    if not ap:
        return m, None
    meta["align_pattern"] = ap[:120]
    meta["align_smarts"] = bool(params.align_pattern_is_smarts)
    if cancel_event is not None and cancel_event.is_set():
        meta["err"] = "cancelled"
        meta["ok"] = False
        return None, "cancelled"
    try:
        nconf = int(m.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf < 2:
        return m, None
    aligned, sp_meta = run_superpose_conformers(
        m,
        SuperposeParams(
            reference_conformer_index=0,
            heavy_atoms_only=True,
            align_pattern=ap,
            align_pattern_is_smarts=bool(params.align_pattern_is_smarts),
        ),
        cancel_event=cancel_event,
    )
    if aligned is None:
        meta["ok"] = False
        meta["err"] = str(sp_meta.get("err") or "align_failed")
        return None, meta["err"]
    for k in ("n_align_atoms", "rms_mean", "rms_max", "ref_cid"):
        if k in sp_meta:
            meta[k] = sp_meta[k]
    return aligned, None
