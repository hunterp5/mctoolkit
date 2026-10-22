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

"""File load, 2D render, and disconnect-fragments workers."""

import csv
import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, wait

from .process_pool_utils import (
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .render2d_pool import (
    ensure_render2d_process_pool,
    note_render2d_pool_busy,
    note_render2d_pool_idle,
    release_render2d_process_pool,
    render2d_process_worker_count,
)

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ..platform_support.config import load_config
from ..chem.render2d_mp import (
    REACTION_PAYLOAD_TAG,
    molecule_image_bytes,
    STRUCTURE_PAYLOAD_TAG,
    mp_render_structure_batch,
)
from ..chem.structure_source_headers import needs_structure_source_picker
from ..table.text_file_ingest import (
    csv_row_to_cells,
    find_smiles_column,
    smi_line_to_cells,
    sniff_table_delimiter,
)
from ..table.open_messages import message_for_read_failure
from ..table.table_file_formats import (
    RXN_EXTS,
    SMI_LINE_EXTS,
    STRUCTURE_MOL_EXTS,
    TABULAR_EXTS,
    default_table_delimiter,
    iter_structure_mols,
    load_xlsx_table,
    logical_suffix,
    open_text_maybe_gzip,
)
from ..conformers.conformer_column_codec import (
    mol_coordinates_fill_blank_confs,
    mol_has_3d_coordinates,
)
from ..chem.fragment_disconnect import largest_fragment_and_rest
from ..chem.structure_2d_depiction import (
    ReactionDrawSpec,
    render_depict_payload_png,
    render_molecule_png,
    render_reaction_png,
)
from ..chem.structure_neutralize import neutralize_mol
from ..chem.structure_hydrogens import add_explicit_hydrogens, remove_explicit_hydrogens
from ..chem.reaction_file_io import RXN_TABLE_HEADERS, load_rxn_file
from ..chem.molecule_conversion import (
    mol_from_tool_input,
    row_cells_from_mol,
    safe_mol_prop_string,
    tool_structure_result,
)
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from .signals import WorkerSignals, emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)

_OPENABLE_TABLE_EXTS = STRUCTURE_MOL_EXTS | SMI_LINE_EXTS | TABULAR_EXTS | RXN_EXTS


def _file_has_bytes(path: str) -> bool:
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def _emit_structure_tool_progress(
    *,
    message: str,
    done: int,
    total: int,
    signals,
    progress_state: ToolProgressState | None,
    throttle: list,
) -> None:
    report_tool_progress(
        message=message,
        done=done,
        total=total,
        progress_state=progress_state,
        signals=signals,
        throttle=throttle,
    )


def mol_to_ingest_blob(mol: "Chem.Mol", *, keep_conformers: bool = False) -> bytes:
    """Serialize a parsed molecule's structure for cross-thread ingest transfer.

    Passing live RDKit Mol objects across the load worker → GUI thread boundary causes multi-second
    UI freezes for large files, so batches carry these lightweight binary blobs instead. Properties
    are intentionally *not* pickled here: they travel in the accompanying cell dict (the table is the
    source of truth for property values), and dropping them makes serialize/rebuild ~4x faster and
    the payload ~10x smaller.

    Depiction-only 2D conformers are dropped here as well. The molecule store keeps connection
    tables, so shipping those coordinates only made the GUI thread strip them one row at a time.
    3D coordinates are kept: ingest packs them into the ``confs`` sidecar. 2D coordinates are kept
    only when *keep_conformers* is set, so a blank ``confs`` cell can store that structure.
    """
    if not keep_conformers and mol.GetNumConformers() and not mol_has_3d_coordinates(mol):
        mol = Chem.Mol(mol)
        mol.RemoveAllConformers()
    return mol.ToBinary()


def _mol_ingest_item(
    mol: "Chem.Mol", data_headers: list[str]
) -> tuple[bytes, dict[str, str], str, bytes]:
    """Ingest payload for one mol: structure blob, cells, SMILES, and flat depiction coordinates.

    Extracting cells and SMILES here keeps that work off the GUI thread and in parallel with
    parsing. The SMILES is the molecule store's structure text, which the Structure cell shows
    until the row is drawn. A structure with coordinates and an empty ``confs`` cell keeps those
    coordinates so ingest can store the structure as that conformation instead of a blank cell.

    Flat 2D coordinates are packed separately. The structure blob still drops them, and the
    GUI stores the pack as the row's depiction orientation. 3D coordinates are not a depiction.
    """
    from ..chem.depiction_coords import depiction_blob_from_mol

    cells = row_cells_from_mol(mol, data_headers)
    confs_cell = cells.get("confs") if "confs" in cells else None
    keep = mol_coordinates_fill_blank_confs(mol, confs_cell)
    try:
        smiles = Chem.MolToSmiles(mol)
    except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
        smiles = ""
    depiction = depiction_blob_from_mol(mol)
    return mol_to_ingest_blob(mol, keep_conformers=keep), cells, smiles, depiction


# Re-export for call sites / tests that still import the private name from this module.
_mp_render_structure_batch = mp_render_structure_batch


def render2d_process_worker_count() -> int:
    """Child-process count for batch 2D rendering (delegates to the shared pool helper)."""
    from .render2d_pool import render2d_process_worker_count as _count

    return _count()


class Render2DBatchHeldJob(QRunnable):
    """
    Process-queue adapter for Chemistry → Render 2D.

    Prepares the batch on the GUI thread, runs subprocess rendering, then blocks until the
    UI has flushed results (``_render2d_batch_done_event``).
    """

    def __init__(self, app, payload: tuple, cancel_event: threading.Event | None) -> None:
        super().__init__()
        self._app = app
        self._payload = payload
        self._cancel_event = cancel_event

    def run(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            return
        done_ev = getattr(self._app, "_render2d_batch_done_event", None)
        if done_ev is not None:
            done_ev.clear()
        try:
            from PyQt5.QtCore import QMetaObject, Qt

            self._app._render2d_queue_payload = self._payload
            self._app._render2d_queue_cancel_event = self._cancel_event
            QMetaObject.invokeMethod(
                self._app,
                "_begin_render2d_batch_from_queue",
                Qt.BlockingQueuedConnection,
            )
        except Exception:
            logger.exception("Render2D batch UI prepare failed")
            if done_ev is not None:
                done_ev.set()
            return
        if done_ev is not None:
            if not getattr(self._app, "render2d_batch_active", lambda: False)():
                done_ev.set()
            else:
                done_ev.wait()


class Render2DBatchProcessWorker(QRunnable):
    """Chemistry → Render 2D: draw structures in subprocesses so the GUI process stays responsive."""

    def __init__(
        self,
        items: list,
        signals: WorkerSignals,
        cancel_event: threading.Event | None,
        batch_session: int,
        *,
        want_scenes: bool = False,
    ):
        super().__init__()
        self.items = list(items)
        self.signals = signals
        self.cancel_event = cancel_event
        self.batch_session = int(batch_session or 0)
        self.want_scenes = bool(want_scenes)

    def build_tasks(self) -> list[tuple]:
        """Serialize the queued mols into ``(rows, w, h, want_scenes)`` child-process tasks.

        Rows are grouped by depict size before batching because a task renders every molecule at one
        size, and zoomed rows are drawn at 2x. *want_scenes* is only set for the Structure column,
        whose stores can paint depiction scenes.
        """
        ev = self.cancel_event
        by_size: dict[tuple[int, int], list[tuple]] = {}
        for oid, mol, w, h in self.items:
            if ev is not None and ev.is_set():
                break
            if isinstance(mol, ReactionDrawSpec):
                blob: bytes | tuple = (REACTION_PAYLOAD_TAG, mol.smarts.encode("utf-8"))
            elif isinstance(mol, tuple):
                blob = mol
            elif isinstance(mol, (bytes, bytearray)):
                blob = bytes(mol)
            else:
                try:
                    blob = mol.ToBinary() if mol is not None else b""
                except Exception:
                    blob = b""
            by_size.setdefault((int(w), int(h)), []).append((int(oid), blob))

        batch_size = max(1, int(load_config().render2d_batch_size))
        tasks: list[tuple] = []
        for (w, h), rows in by_size.items():
            for start in range(0, len(rows), batch_size):
                tasks.append((rows[start : start + batch_size], w, h, self.want_scenes))
        return tasks

    def run(self) -> None:
        ev = self.cancel_event
        tasks = self.build_tasks()
        if not tasks:
            return

        proc_workers = render2d_process_worker_count()
        max_inflight = min(48, max(proc_workers * 4, proc_workers))

        it = iter(tasks)
        pending = set()
        ex = ensure_render2d_process_pool(max_workers=proc_workers)
        if ex is None:
            return
        note_render2d_pool_busy()

        def _fill() -> None:
            while len(pending) < max_inflight:
                t = next(it, None)
                if t is None:
                    break
                pending.add(ex.submit(mp_render_structure_batch, t))

        try:
            _fill()
            while pending:
                if should_terminate_process_pool(ev):
                    for f in pending:
                        f.cancel()
                    break
                completed, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for f in completed:
                    if f.cancelled():
                        continue
                    try:
                        rows = f.result()
                    except Exception:
                        logger.exception("Render2D batch subprocess task failed")
                        continue
                    if rows:
                        # One signal per batch: a queued emission per molecule made the GUI thread
                        # the bottleneck on large tables.
                        self.signals.rendered_batch.emit(rows, self.batch_session)
                _fill()
        finally:
            # The pool stays up briefly so the next Render 2D does not pay spawn again, then
            # the idle timer releases it. Cancel / app exit kills workers immediately.
            if should_terminate_process_pool(ev):
                release_render2d_process_pool(kill_workers=True)
            else:
                note_render2d_pool_idle()


class UniversalLoadWorker(QRunnable):
    def __init__(
        self,
        path,
        signals,
        batch_size=400,
        cancel_event: threading.Event | None = None,
        structure_choice_event: threading.Event | None = None,
        ingest_generation: int = 0,
    ):
        super().__init__()
        self.path, self.signals, self.batch_size = path, signals, batch_size
        self.cancel_event = cancel_event
        self.structure_choice_event = structure_choice_event
        self.ingest_generation = int(ingest_generation)

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _wait_for_structure_source_choice(self, headers: list[str]) -> bool:
        """Pause the reader until the UI picks a structure column (or load is cancelled)."""
        ev = self.structure_choice_event
        if ev is None or not needs_structure_source_picker(headers):
            return True
        ev.clear()
        try:
            self.signals.structure_source_probe.emit(list(headers))
        except Exception:
            logger.exception("structure_source_probe emit failed")
            ev.set()
            return True
        while True:
            if ev.wait(timeout=0.2):
                return True
            if self._cancelled():
                ev.set()
                return False

    def run(self):
        try:
            self.signals.tool_progress.emit("Reading file…", -1, -1)
        except Exception:
            pass
        ext = logical_suffix(self.path)
        batch_size = self.batch_size
        cfg = load_config()
        text_first = bool(cfg.ingest_csv_text_first)
        try:
            if ext not in _OPENABLE_TABLE_EXTS:
                raise ValueError(f"Unsupported file type: {ext or '(none)'}")
            headers = ["ID_HIDDEN", "Structure"]
            first_emit = True
            batch = []

            def _flush(*, last: bool) -> None:
                nonlocal first_emit, batch
                if batch:
                    self.signals.mols_loaded.emit(
                        batch, headers if first_emit else [], first_emit, last
                    )
                    first_emit = False
                    batch = []
                elif last and first_emit:
                    self.signals.mols_loaded.emit([], headers, True, True)
                elif last:
                    self.signals.mols_loaded.emit([], [], False, True)

            def _add_mol(mol: Chem.Mol) -> bool:
                nonlocal headers
                if first_emit and len(batch) == 0:
                    headers.extend(sorted(str(p) for p in mol.GetPropNames()))
                    if not self._wait_for_structure_source_choice(headers):
                        return False
                batch.append(_mol_ingest_item(mol, headers[2:]))
                if len(batch) >= batch_size:
                    _flush(last=False)
                return True

            def _add_table_rows(fieldnames: list[str], rows) -> None:
                nonlocal headers
                smi_col = find_smiles_column(fieldnames)
                if smi_col:
                    headers.append("SMILES")
                    headers.extend([h for h in fieldnames if h != smi_col])
                    if not self._wait_for_structure_source_choice(headers):
                        return
                for row in rows:
                    if self._cancelled() or smi_col is None:
                        break
                    if text_first:
                        cells = csv_row_to_cells(row, smi_col=smi_col, fieldnames=fieldnames)
                        if cells is None:
                            continue
                        batch.append(cells)
                    else:
                        m = Chem.MolFromSmiles(row[smi_col])
                        if m:
                            m.SetProp("SMILES", row[smi_col])
                            for h in fieldnames:
                                if h != smi_col:
                                    m.SetProp(h, str(row[h]))
                            batch.append(_mol_ingest_item(m, headers[2:]))
                    if len(batch) >= batch_size:
                        _flush(last=False)

            if ext in STRUCTURE_MOL_EXTS:
                n_mol = 0
                for mol in iter_structure_mols(self.path):
                    if self._cancelled():
                        break
                    n_mol += 1
                    if not _add_mol(mol):
                        break
                if n_mol == 0 and not self._cancelled() and _file_has_bytes(str(self.path)):
                    raise ValueError("No structures could be read.")
            elif ext in SMI_LINE_EXTS and text_first:
                headers.append("SMILES")
                if self._wait_for_structure_source_choice(headers):
                    with open_text_maybe_gzip(self.path) as f:
                        for line in f:
                            if self._cancelled():
                                break
                            cells = smi_line_to_cells(line)
                            if cells is None:
                                continue
                            batch.append(cells)
                            if len(batch) >= batch_size:
                                _flush(last=False)
            elif ext == ".xlsx":
                fieldnames, rows = load_xlsx_table(self.path)
                _add_table_rows(fieldnames, rows)
            elif ext in TABULAR_EXTS or ext in SMI_LINE_EXTS:
                default_delim = default_table_delimiter(ext)
                with open_text_maybe_gzip(self.path) as f:
                    sample = f.read(65536)
                    f.seek(0)
                    delim = sniff_table_delimiter(sample, default=default_delim)
                    reader = csv.DictReader(f, delimiter=delim)
                    fieldnames = list(reader.fieldnames or [])
                    _add_table_rows(fieldnames, reader)
            elif ext in RXN_EXTS:
                headers.extend(list(RXN_TABLE_HEADERS))
                records = load_rxn_file(self.path)
                if records and not self._wait_for_structure_source_choice(headers):
                    records = []
                items: list = []
                for rec in records:
                    if rec.mol is not None:
                        items.append(_mol_ingest_item(rec.mol, headers[2:]))
                    else:
                        items.append(
                            {
                                RXN_TABLE_HEADERS[0]: rec.smarts,
                                RXN_TABLE_HEADERS[1]: rec.reactants,
                                RXN_TABLE_HEADERS[2]: rec.products,
                                RXN_TABLE_HEADERS[3]: rec.name,
                            }
                        )
                if items and any(isinstance(x, dict) for x in items):
                    unified: list[dict[str, str]] = []
                    for item in items:
                        if isinstance(item, dict):
                            unified.append(item)
                        else:
                            unified.append(item[1])
                    items = unified
                for rec_item in items:
                    if self._cancelled():
                        break
                    batch.append(rec_item)
                    if len(batch) >= batch_size:
                        _flush(last=False)

            _flush(last=True)
        except Exception as exc:
            logger.exception("UniversalLoadWorker failed: %s", self.path)
            try:
                self.signals.file_load_failed.emit(
                    int(self.ingest_generation),
                    message_for_read_failure(str(self.path), exc),
                )
            except Exception:
                logger.warning("UniversalLoadWorker: failed to emit load failure", exc_info=True)


class RenderWorker(QRunnable):
    def __init__(
        self,
        compound_oid,
        mol,
        signals,
        width=None,
        height=None,
        props=None,
        cancel_event: threading.Event | None = None,
        skip_mol_props: bool = False,
        render_batch_session: int = 0,
        want_scene: bool = False,
    ):
        """Draw one Structure cell. With *want_scene* a molecule is emitted as its packed
        depiction scene when the builder can draw it, as Render 2D batches do."""
        super().__init__()
        self.compound_oid = int(compound_oid)
        self.mol = mol
        self.signals = signals
        self.w = int(width if width is not None else structure_depict_width())
        self.h = int(height if height is not None else structure_depict_height())
        self.props = props
        self.cancel_event = cancel_event
        self.skip_mol_props = skip_mol_props
        self.render_batch_session = int(render_batch_session or 0)
        self.want_scene = bool(want_scene)

    def run(self):
        sid = self.render_batch_session
        oid = self.compound_oid
        if self.cancel_event is not None and self.cancel_event.is_set():
            try:
                self.signals.rendered.emit(oid, {}, b"", False, self.w, self.h, sid)
            except Exception:
                pass
            return
        try:
            if self.skip_mol_props or isinstance(self.mol, ReactionDrawSpec):
                p = {}
            elif self.props is not None:
                p = self.props
            else:
                p = {n: safe_mol_prop_string(self.mol, n) for n in self.mol.GetPropNames()}
            if isinstance(self.mol, ReactionDrawSpec):
                image = render_depict_payload_png(self.mol, self.w, self.h)
            else:
                image = molecule_image_bytes(self.mol, self.w, self.h, want_scene=self.want_scene)
            self.signals.rendered.emit(oid, p, image, True, self.w, self.h, sid)
        except Exception:
            self.signals.rendered.emit(oid, {}, b"", False, self.w, self.h, sid)


class DisconnectFragmentsWorker(QRunnable):
    """Keep the largest fragment and record smaller fragments for each row.

    Rows are ``(oid, mol_or_blob_or_text[, source_text])``, or ``(oid, cell_text)`` when
    *is_smiles*. Emits ``(oid, parent_blob, fragments, parent_smiles)`` per kept row.
    """

    def __init__(
        self,
        mols_data,
        signals,
        is_smiles: bool = False,
        cancel_event: threading.Event | None = None,
        *,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.mols_data, self.signals, self.is_smiles = mols_data, signals, is_smiles
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def run(self):
        items = list(self.mols_data)
        total = max(len(items), 1)
        res = []
        done_count = 0
        cancelled = False
        for done, row in enumerate(items, start=1):
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                break
            done_count = done
            oid = row[0]
            if self.is_smiles:
                source_text = str(row[1] or "").strip() or None
                mol = mol_from_tool_input(source_text)
            else:
                mol = mol_from_tool_input(row[1])
                source_text = (str(row[2]).strip() if len(row) >= 3 and row[2] else None) or None
            if mol is None and source_text:
                mol = mol_from_tool_input(source_text)
            if mol is None:
                _emit_structure_tool_progress(
                    message="Disconnect fragments…",
                    done=done,
                    total=total,
                    signals=self.signals,
                    progress_state=self.progress_state,
                    throttle=self._progress_throttle,
                )
                continue
            parent, fragments = largest_fragment_and_rest(mol, source_text)
            if parent is None:
                _emit_structure_tool_progress(
                    message="Disconnect fragments…",
                    done=done,
                    total=total,
                    signals=self.signals,
                    progress_state=self.progress_state,
                    throttle=self._progress_throttle,
                )
                continue
            packed = tool_structure_result(oid, parent)
            if packed is not None:
                res.append((packed[0], packed[1], fragments, packed[2]))
            _emit_structure_tool_progress(
                message="Disconnect fragments…",
                done=done,
                total=total,
                signals=self.signals,
                progress_state=self.progress_state,
                throttle=self._progress_throttle,
            )
        emit_partial_results_if_cancelled(
            self.signals, "Disconnect fragments", done_count, total, cancelled
        )
        self.signals.disconnect_fragments_finished.emit(res)


class NeutralizeWorker(QRunnable):
    """Neutralize each ``(oid, mol_or_blob_or_text)`` row; emits ``(oid, blob, smiles)`` rows."""

    def __init__(
        self,
        mols_data,
        signals,
        is_smiles: bool = False,
        cancel_event: threading.Event | None = None,
        *,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.mols_data, self.signals, self.is_smiles = mols_data, signals, is_smiles
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def run(self):
        items = list(self.mols_data)
        total = max(len(items), 1)
        res: list[tuple[int, object]] = []
        done_count = 0
        cancelled = False
        for done, row in enumerate(items, start=1):
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                break
            done_count = done
            oid = row[0]
            mol = mol_from_tool_input(row[1])
            if mol is None:
                _emit_structure_tool_progress(
                    message="Neutralize…",
                    done=done,
                    total=total,
                    signals=self.signals,
                    progress_state=self.progress_state,
                    throttle=self._progress_throttle,
                )
                continue
            packed = tool_structure_result(oid, neutralize_mol(mol))
            if packed is not None:
                res.append(packed)
            _emit_structure_tool_progress(
                message="Neutralize…",
                done=done,
                total=total,
                signals=self.signals,
                progress_state=self.progress_state,
                throttle=self._progress_throttle,
            )
        emit_partial_results_if_cancelled(self.signals, "Neutralize", done_count, total, cancelled)
        self.signals.neutralized.emit(res)


class AddExplicitHydrogensWorker(QRunnable):
    """Expand implicit hydrogens to explicit atoms for each structure in ``mols_data``."""

    def __init__(
        self,
        mols_data,
        signals,
        is_smiles: bool = False,
        cancel_event: threading.Event | None = None,
        *,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.mols_data, self.signals, self.is_smiles = mols_data, signals, is_smiles
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def run(self):
        items = list(self.mols_data)
        total = max(len(items), 1)
        res: list[tuple[int, object]] = []
        done_count = 0
        cancelled = False
        for done, row in enumerate(items, start=1):
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                break
            done_count = done
            oid = row[0]
            mol = mol_from_tool_input(row[1])
            if mol is None:
                _emit_structure_tool_progress(
                    message="Add explicit hydrogens…",
                    done=done,
                    total=total,
                    signals=self.signals,
                    progress_state=self.progress_state,
                    throttle=self._progress_throttle,
                )
                continue
            packed = tool_structure_result(oid, add_explicit_hydrogens(mol))
            if packed is not None:
                res.append(packed)
            _emit_structure_tool_progress(
                message="Add explicit hydrogens…",
                done=done,
                total=total,
                signals=self.signals,
                progress_state=self.progress_state,
                throttle=self._progress_throttle,
            )
        emit_partial_results_if_cancelled(
            self.signals, "Add explicit hydrogens", done_count, total, cancelled
        )
        self.signals.explicit_hydrogens_added.emit(res)


class RemoveExplicitHydrogensWorker(QRunnable):
    """Remove explicit hydrogen atoms from each structure in ``mols_data``."""

    def __init__(
        self,
        mols_data,
        signals,
        is_smiles: bool = False,
        cancel_event: threading.Event | None = None,
        *,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.mols_data, self.signals, self.is_smiles = mols_data, signals, is_smiles
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def run(self):
        items = list(self.mols_data)
        total = max(len(items), 1)
        res: list[tuple[int, object]] = []
        done_count = 0
        cancelled = False
        for done, row in enumerate(items, start=1):
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                break
            done_count = done
            oid = row[0]
            mol = mol_from_tool_input(row[1])
            if mol is None:
                _emit_structure_tool_progress(
                    message="Remove explicit hydrogens…",
                    done=done,
                    total=total,
                    signals=self.signals,
                    progress_state=self.progress_state,
                    throttle=self._progress_throttle,
                )
                continue
            packed = tool_structure_result(oid, remove_explicit_hydrogens(mol))
            if packed is not None:
                res.append(packed)
            _emit_structure_tool_progress(
                message="Remove explicit hydrogens…",
                done=done,
                total=total,
                signals=self.signals,
                progress_state=self.progress_state,
                throttle=self._progress_throttle,
            )
        emit_partial_results_if_cancelled(
            self.signals, "Remove explicit hydrogens", done_count, total, cancelled
        )
        self.signals.explicit_hydrogens_removed.emit(res)
