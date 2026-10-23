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

"""Fast Prepare worker: disconnect largest fragment, optional neutralize, in one parallel pass.

Fast Prepare used to run the disconnect and neutralize tools as two sequential jobs, each
processing every row on a single thread and each writing its results back to the table (the first
writeback being immediately overwritten by the second). Both steps are pure per-molecule CPU work,
so they run here as one batched pass in child processes — the same pattern the descriptor worker
uses — which keeps RDKit off the GUI thread and off the GIL. Neutralize is optional (off by default).

Results carry molecules as binary blobs rather than live ``Chem.Mol`` objects: child processes have
to serialize anyway, and handing thousands of live SWIG-wrapped mols across a Qt queued connection
stalls the GUI for seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..chem.depiction_builder import build_scene
from ..chem.depiction_coords import apply_depiction_coords, depiction_blob_from_mol
from ..chem.depiction_layout import LayoutOptions, current_layout_options, layout_for_drawing
from ..chem.depiction_scene import pack_scene
from ..chem.fragment_disconnect import largest_fragment_and_rest
from ..chem.structure_neutralize import neutralize_mol
from ..chem.molecule_conversion import (
    mol_graph_binary,
    mol_to_canonical_smiles,
    parse_molecule_from_cell_text,
)
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import WorkerSignals, emit_partial_results_if_cancelled
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress

logger = logging.getLogger(__name__)

PROGRESS_LABEL = "Preparing structures…"
TOOL_LABEL = "Fast prepare"


@dataclass(frozen=True)
class FastPrepareParams:
    """Job flags for :class:`FastPrepareWorker` (not the row payloads)."""

    is_smiles: bool = False
    need_smiles: bool = False
    neutralize: bool = False
    batch_size: int = 64
    process_pool_min_rows: int = 250
    # Structure output only. The scene is built here, while the molecule still has coordinates,
    # so the GUI does not start a second render pass that would lay every row out again.
    want_scene: bool = False


def _packed_scene(mol, stored_blob: bytes, layout: LayoutOptions | None) -> tuple[bytes, bytes]:
    """``(scene, xy)`` for the molecule that will actually be stored.

    The scene is built from *stored_blob* plus the float32 coordinates a later Render 2D will
    reapply, so that redraw is the same picture. ``xy`` is empty when the layout added atoms
    (stereo hydrogens) and no longer matches the stored connection table; the scene is then built
    from the laid-out molecule and a later redraw generates coordinates again.
    """
    options = layout if layout is not None else current_layout_options()
    laid = layout_for_drawing(mol, options)
    xy = b""
    draw = laid
    try:
        same_atoms = int(laid.GetNumAtoms()) == int(mol.GetNumAtoms())
    except (AttributeError, TypeError, ValueError):
        same_atoms = False
    if same_atoms:
        xy = depiction_blob_from_mol(laid)
    if xy and stored_blob:
        restored = Chem.Mol(bytes(stored_blob))
        if restored is not None and int(restored.GetNumAtoms()) == int(mol.GetNumAtoms()):
            applied = apply_depiction_coords(restored, xy)
            if applied is not restored:
                draw = applied
            else:
                xy = b""
    else:
        xy = b""
    scene, _reason = build_scene(draw, options)
    packed = b""
    if scene is not None:
        try:
            packed = pack_scene(scene)
        except ValueError:
            packed = b""
    return packed, xy


def _prepare_one(
    blob_or_text: bytes | str,
    source_text: str | None,
    *,
    is_text: bool,
    need_smiles: bool,
    neutralize: bool = False,
    want_scene: bool = False,
    layout: LayoutOptions | None = None,
) -> tuple | None:
    """Disconnect the largest fragment, then optionally neutralize it.

    Returns ``(mol_blob, smaller_fragments_text, canonical_smiles)``, or ``None`` when the row has
    no usable structure. If neutralization is requested and fails, the disconnected parent is kept.
    With *want_scene* the tuple also carries ``(packed_scene, packed_xy)``, built before the
    connection-table blob drops the conformer.
    """
    if is_text:
        raw = str(blob_or_text or "").strip()
        mol = parse_molecule_from_cell_text(raw) if raw else None
        source_text = source_text or (raw or None)
    else:
        mol = Chem.Mol(blob_or_text) if blob_or_text else None
        if mol is None and source_text:
            mol = parse_molecule_from_cell_text(source_text)
    if mol is None:
        return None
    parent, fragments = largest_fragment_and_rest(mol, source_text)
    if parent is None:
        return None
    out = parent
    if neutralize:
        out = neutralize_mol(parent) or parent
    smiles = mol_to_canonical_smiles(out) if need_smiles else ""
    blob = mol_graph_binary(out) or out.ToBinary()
    if not want_scene:
        return blob, fragments, smiles
    scene, xy = _packed_scene(out, blob, layout)
    return blob, fragments, smiles, scene, xy


def _mp_fast_prepare_batch(args: tuple) -> list[tuple]:
    """Run :func:`_prepare_one` over one batch inside a child process (picklable args)."""
    items, is_text, need_smiles, neutralize = args[:4]
    want_scene = bool(args[4]) if len(args) > 4 else False
    layout = current_layout_options() if want_scene else None
    out: list[tuple] = []
    for oid, payload, source_text in items:
        try:
            res = _prepare_one(
                payload,
                source_text,
                is_text=bool(is_text),
                need_smiles=bool(need_smiles),
                neutralize=bool(neutralize),
                want_scene=want_scene,
                layout=layout,
            )
        except Exception:
            res = None
        if res is None:
            continue
        out.append((int(oid), *res))
    return out


class FastPrepareWorker(QRunnable):
    """Disconnect (and optionally neutralize) every row in ``items``, batched across child processes.

    ``items`` are ``(oid, structure, source_text)`` tuples, where ``structure`` is a stored mol
    blob (preferred: the GUI thread never has to hydrate it) or a live mol, or
    ``(oid, cell_text)`` when ``params.is_smiles``. Without scenes, emits ``signals.fast_prepared``
    once with ``(oid, mol_blob, fragments_text, canonical_smiles)`` rows. With scenes, emits
    ``signals.fast_prepared_batch`` per completed chunk as
    ``(oid, mol_blob, fragments_text, canonical_smiles, scene, xy)``, then an empty last batch.
    Blobs are connection-table only, matching what :class:`~molmanager.storage.mol_store.MolStore`
    stores.
    """

    def __init__(
        self,
        items: list,
        params: FastPrepareParams,
        signals: WorkerSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.items = list(items)
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]
        self._buffered: list[tuple] = []
        self._streamed = False

    def _emit_progress(self, done: int, total: int) -> None:
        report_tool_progress(
            message=PROGRESS_LABEL,
            done=int(done),
            total=int(total),
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=self._progress_throttle,
        )

    def _tasks(self) -> list[tuple[int, object, str | None]]:
        """Serialize input rows into picklable ``(oid, payload, source_text)`` tuples."""
        tasks: list[tuple[int, object, str | None]] = []
        for row in self.items:
            oid = int(row[0])
            if self.params.is_smiles:
                tasks.append((oid, str(row[1] or ""), None))
                continue
            structure = row[1]
            source_text = (str(row[2]).strip() or None) if len(row) >= 3 and row[2] else None
            if isinstance(structure, (bytes, bytearray)):
                blob = bytes(structure)
            else:
                try:
                    blob = structure.ToBinary() if structure is not None else b""
                except Exception:
                    blob = b""
            tasks.append((oid, blob, source_text))
        return tasks

    def _accept_rows(self, rows: list[tuple]) -> None:
        """Hand one completed chunk to the GUI, or hold it for the single finish signal."""
        if not rows:
            return
        signal = None
        if self.params.want_scene:
            signal = getattr(self.signals, "fast_prepared_batch", None)
        if signal is None:
            self._buffered.extend(rows)
            return
        signal.emit(list(rows), False)
        self._streamed = True

    def _emit_finished(self, done: int, total: int, cancelled: bool) -> None:
        self._emit_progress(done, total)
        delivered = done if self._streamed else len(self._buffered)
        emit_partial_results_if_cancelled(self.signals, TOOL_LABEL, delivered, total, cancelled)
        if self._streamed:
            self.signals.fast_prepared_batch.emit([], True)
            return
        self.signals.fast_prepared.emit(self._buffered)

    def run(self) -> None:
        tasks = self._tasks()
        total = max(len(tasks), 1)
        if not tasks:
            self._emit_finished(0, total, False)
            return

        p = self.params
        batch_size = max(1, int(p.batch_size))
        batches = [
            (tasks[s : s + batch_size], p.is_smiles, p.need_smiles, p.neutralize, p.want_scene)
            for s in range(0, len(tasks), batch_size)
        ]
        from ..platform_support.worker_budget import rdkit_process_workers

        workers = rdkit_process_workers(hard_cap=6)
        use_pool = len(tasks) >= max(2, int(p.process_pool_min_rows)) and workers > 1

        done = 0
        cancelled = False
        self._emit_progress(0, total)

        if use_pool:
            try:
                done, cancelled = self._run_pool(batches, total, workers)
            except Exception:
                logger.exception("Process-pool fast prepare failed; falling back to in-process")
                if self._streamed or self._buffered:
                    cancelled = True
                else:
                    use_pool = False
                    done, cancelled = 0, False
        if not use_pool:
            done, cancelled = self._run_inline(batches, total)

        self._emit_finished(done, total, cancelled)

    def _run_pool(self, batches: list[tuple], total: int, workers: int):
        """Batch the work across child processes, streaming progress as futures land."""
        max_inflight = min(48, max(workers * 4, workers))
        it = iter(batches)
        pending: set = set()
        done = 0
        cancelled = False
        ev = self.cancel_event
        ex = register_process_pool(ProcessPoolExecutor(max_workers=workers))

        def _fill() -> None:
            while len(pending) < max_inflight:
                nxt = next(it, None)
                if nxt is None:
                    break
                pending.add(ex.submit(_mp_fast_prepare_batch, nxt))

        try:
            _fill()
            last_pulse = 0.0
            while pending:
                if should_terminate_process_pool(ev):
                    cancelled = True
                    for f in list(pending):
                        f.cancel()
                    break
                completed, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for f in completed:
                    if f.cancelled():
                        continue
                    try:
                        rows = f.result()
                    except Exception:
                        logger.exception("Fast prepare subprocess batch failed")
                        continue
                    self._accept_rows(rows)
                    done += len(rows)
                if completed:
                    self._emit_progress(min(done, total), total)
                elif pending:
                    now = time.monotonic()
                    if now - last_pulse >= 0.55:
                        last_pulse = now
                        self._emit_progress(min(done, total), total)
                _fill()
        finally:
            shutdown_process_pool_executor(ex, kill_workers=should_terminate_process_pool(ev))
        return done, cancelled

    def _run_inline(self, batches: list[tuple], total: int):
        """Same work in this thread — used for small jobs and as a process-pool fallback."""
        done = 0
        cancelled = False
        for batch in batches:
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                break
            rows = _mp_fast_prepare_batch(batch)
            self._accept_rows(rows)
            done += len(batch[0])
            self._emit_progress(min(done, total), total)
        return done, cancelled
