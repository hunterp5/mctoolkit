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
from collections import deque
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, wait
from concurrent.futures import TimeoutError as FutureTimeoutError

from .process_pool_utils import (
    should_terminate_process_pool,
)
from .render2d_pool import (
    ensure_render2d_process_pool,
    note_render2d_pool_busy,
    note_render2d_pool_idle,
    release_render2d_process_pool,
    render2d_process_worker_count,
)
from .render2d_plan import PriorityRenderPlan

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ..platform_support.config import load_config
from ..chem.render2d_mp import (
    REACTION_PAYLOAD_TAG,
    molecule_image_bytes,
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
    MOL2_EXTS,
    OPENABLE_TABLE_EXTS,
    RXN_EXTS,
    SDF_EXTS,
    SMI_LINE_EXTS,
    STRUCTURE_MOL_EXTS,
    TABULAR_EXTS,
    default_table_delimiter,
    iter_structure_mols,
    load_xlsx_table,
    logical_suffix,
    open_text_maybe_gzip,
)
from ..chem.ingest_records import (
    IngestRecord,
    ingest_record_from_mol,
    iter_chunk_mols,
    parse_structure_chunk,
    structure_file_chunks,
)
from ..chem.fragment_disconnect import largest_fragment_and_rest
from ..chem.structure_2d_depiction import (
    ReactionDrawSpec,
    render_depict_payload_png,
)
from ..chem.structure_neutralize import neutralize_mol
from ..chem.structure_hydrogens import add_explicit_hydrogens, remove_explicit_hydrogens
from ..chem.reaction_file_io import RXN_TABLE_HEADERS, load_rxn_file
from ..chem.molecule_conversion import (
    mol_from_tool_input,
    safe_mol_prop_string,
    tool_structure_result,
)
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from .signals import WorkerSignals, emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)

#: Below this size an SDF or MOL2 is parsed on the load thread; worker processes would
#: cost more to feed than they save.
_PARALLEL_PARSE_MIN_BYTES = 4 << 20

#: Rows per task for on-screen rows, small enough that every process draws part of the
#: viewport.
_PRIORITY_RENDER_BATCH_SIZE = 8


def _parallel_parse_kind(path: str, ext: str) -> str | None:
    """``"sdf"`` or ``"mol2"`` when *path* is large and seekable enough to parse in processes."""
    if str(path).lower().endswith(".gz"):
        return None
    kind = "sdf" if ext in SDF_EXTS else "mol2" if ext in MOL2_EXTS else None
    if kind is None:
        return None
    try:
        big = os.path.getsize(path) >= _PARALLEL_PARSE_MIN_BYTES
    except OSError:
        return None
    return kind if big else None


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
                return
            # The GUI sets the event; once the app is closing it never will.
            while not done_ev.wait(timeout=0.2):
                if should_terminate_process_pool(self._cancel_event):
                    return


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
        self._plan_lock = threading.Lock()
        self._plan: PriorityRenderPlan | None = None
        self._priority_request: list[int] = []

    def prioritize(self, oids: Iterable[int]) -> None:
        """Draw *oids* next (GUI thread). Safe to call before the worker starts."""
        request = [int(oid) for oid in oids]
        with self._plan_lock:
            self._priority_request = request
            plan = self._plan
        if plan is not None:
            plan.prioritize(request)

    def build_tasks(self) -> list[tuple]:
        """Every child-process task in submission order (see :meth:`build_plan`)."""
        return list(iter(self.build_plan().next_task, None))

    def build_plan(self) -> PriorityRenderPlan:
        """Serialize the queued mols into a :class:`PriorityRenderPlan` of render tasks.

        *want_scenes* is only set for the Structure column, whose stores can paint
        depiction scenes.
        """
        ev = self.cancel_event
        rows: list[tuple[int, object, int, int]] = []
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
            rows.append((int(oid), blob, int(w), int(h)))
        return PriorityRenderPlan(
            rows,
            batch_size=load_config().render2d_batch_size,
            priority_batch_size=_PRIORITY_RENDER_BATCH_SIZE,
            want_scenes=self.want_scenes,
        )

    def run(self) -> None:
        ev = self.cancel_event
        plan = self.build_plan()
        with self._plan_lock:
            self._plan = plan
            plan.prioritize(self._priority_request)
        if not len(plan):
            return

        proc_workers = render2d_process_worker_count()
        # Few tasks wait in the pool so rows scrolled into view are drawn soon after.
        max_inflight = proc_workers * 2

        pending = set()
        ex = ensure_render2d_process_pool(max_workers=proc_workers)
        if ex is None:
            return
        note_render2d_pool_busy()

        def _fill() -> None:
            while len(pending) < max_inflight:
                t = plan.next_task()
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

    def _parse_chunks_in_processes(self, tasks: list[tuple], on_records) -> int:
        """Parse SDF/MOL2 byte ranges in the shared worker pool; deliver records in file order.

        A task the pool cannot run is parsed on this thread instead. Returns the record count.
        """
        pool = ensure_render2d_process_pool()
        if pool is None:
            return 0
        note_render2d_pool_busy()
        window = max(2, 2 * render2d_process_worker_count())
        pending: deque = deque()
        remaining = iter(tasks)
        n_records = 0

        def _fill() -> None:
            while len(pending) < window:
                task = next(remaining, None)
                if task is None:
                    return
                pending.append((task, pool.submit(parse_structure_chunk, task)))

        try:
            _fill()
            while pending:
                if self._cancelled():
                    for _task, future in pending:
                        future.cancel()
                    break
                task, future = pending[0]
                try:
                    records = future.result(timeout=0.2)
                except FutureTimeoutError:
                    continue
                except Exception:  # noqa: BLE001 — a broken pool must not lose the chunk
                    logger.warning("Parse task failed in the pool; parsing it here", exc_info=True)
                    records = parse_structure_chunk(task)
                pending.popleft()
                _fill()
                n_records += len(records)
                on_records(records)
        finally:
            note_render2d_pool_idle()
        return n_records

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
            if ext not in OPENABLE_TABLE_EXTS:
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
                batch.append(ingest_record_from_mol(mol, headers[2:]))
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
                            batch.append(ingest_record_from_mol(m, headers[2:]))
                    if len(batch) >= batch_size:
                        _flush(last=False)

            if ext in STRUCTURE_MOL_EXTS:
                n_mol = 0
                kind = _parallel_parse_kind(str(self.path), ext)
                chunks = structure_file_chunks(str(self.path), kind) if kind else []
                if len(chunks) > 1:
                    # Headers come from the first molecule, so read on this thread until one parses.
                    stopped = False
                    head = 0
                    with open(self.path, "rb") as fh:
                        while head < len(chunks) and n_mol == 0 and not stopped:
                            start, end = chunks[head]
                            fh.seek(start)
                            for mol in iter_chunk_mols(fh.read(end - start), kind):
                                n_mol += 1
                                if self._cancelled() or not _add_mol(mol):
                                    stopped = True
                                    break
                            head += 1
                    if not stopped and head < len(chunks):
                        _flush(last=False)

                        def _add_records(records: list[IngestRecord]) -> None:
                            batch.extend(records)
                            _flush(last=False)

                        tasks = [
                            (str(self.path), kind, a, b, headers[2:]) for a, b in chunks[head:]
                        ]
                        n_mol += self._parse_chunks_in_processes(tasks, _add_records)
                else:
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
                        items.append(ingest_record_from_mol(rec.mol, headers[2:]))
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
