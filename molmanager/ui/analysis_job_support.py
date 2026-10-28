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

"""Shared enqueue / record prep / finish handlers for analysis and predict tools.

Thin UI adapters (mixins and dialogs) call these helpers so dialog → scoped mols →
process-queue wiring stays in one place (AnalysisJobRunner pattern without a heavy class).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QMessageBox
from rdkit import Chem

from ..chem.structure_payload import (
    StructurePayload,
    mol_from_payload,
    oid_mol_rows_from_payloads,
)
from ..services.table_reader import activity_for_oid
from ..workflows.scoped_records import (
    ScopeBlocker,
    plan_scoped_activity_records,
    plan_scoped_structure_records,
)
from ..workflows.tool_readiness import ToolBlocker, plan_activity_analysis, plan_table_readiness
from .table_reader_view import WindowTableReader
from .tool_dialog_scope import abort_if_only_selected_but_empty, prepare_tool_dialog

WorkerFactory = Callable[..., Any]

_BLOCKER_TEXT = {
    ToolBlocker.NO_TABLE: "Open a file or start a session first.",
    ToolBlocker.NO_ROWS: "Load a table with at least one row first.",
}


def activity_value_for_table_oid(
    app: Any,
    oid: int,
    *,
    activity_column: str,
    activity_col_index: int,
) -> float | None:
    """Read a numeric activity for *oid* from cell text or backing value."""
    return activity_for_oid(
        WindowTableReader(app),
        oid,
        activity_column=activity_column,
        activity_col_index=activity_col_index,
    )


def ensure_table_ready_for_tool(
    app: Any,
    tool_label: str,
    *,
    require_rows: bool = False,
    empty_message: str | None = None,
) -> bool:
    """Return True when the table can host *tool_label*; otherwise inform and return False."""
    plan = plan_table_readiness(
        headers=app.headers,
        row_count=app._table_model.rowCount(),
        require_rows=require_rows,
    )
    if plan.is_ready:
        return True
    QMessageBox.information(app, tool_label, empty_message or _BLOCKER_TEXT[plan.blocked_by])
    return False


def ensure_activity_analysis_ready(
    app: Any,
    tool_label: str,
    *,
    missing_activity_message: str,
) -> list[str] | None:
    """Return numeric activity columns, or ``None`` after informing the user."""
    from .dialogs.mmp import activity_columns_for_mmp

    plan = plan_activity_analysis(
        headers=app.headers,
        row_count=app._table_model.rowCount(),
        activity_columns=activity_columns_for_mmp(app, only_selected=False),
    )
    if plan.is_ready:
        return list(plan.activity_columns)
    message = (
        missing_activity_message
        if plan.blocked_by is ToolBlocker.NO_ACTIVITY_COLUMN
        else "Load a table with at least one row first."
    )
    QMessageBox.information(app, tool_label, message)
    return None


def show_activity_tool_dialog(
    app: Any,
    dialog: QDialog,
    *,
    on_accepted: Callable[[QDialog], None],
) -> None:
    """Standard modeless tool-dialog show + accepted handoff."""
    prepare_tool_dialog(app, dialog)
    dialog.setAttribute(Qt.WA_DeleteOnClose, True)
    dialog.accepted.connect(lambda *_, dlg=dialog: on_accepted(dlg))
    dialog.show()


def prepare_scoped_structure_mols(
    app: Any,
    *,
    tool_label: str,
    structure_source: str,
    only_selected: bool,
    min_mols: int = 1,
    empty_message: str | None = None,
    too_few_message: str | None = None,
) -> list[tuple[int, Chem.Mol]] | None:
    """Validate scope and collect ``(oid, mol)`` pairs for structure-only jobs.

    Hydrates on the caller thread. Queued tools should use
    :func:`prepare_scoped_structure_payloads` and hydrate in the worker factory.
    Returns ``None`` after informing the user when the job should not start.
    """
    payloads = prepare_scoped_structure_payloads(
        app,
        tool_label=tool_label,
        structure_source=structure_source,
        only_selected=only_selected,
        min_mols=min_mols,
        empty_message=empty_message,
        too_few_message=too_few_message,
    )
    if payloads is None:
        return None
    return oid_mol_rows_from_payloads(payloads)


def prepare_scoped_structure_payloads(
    app: Any,
    *,
    tool_label: str,
    structure_source: str,
    only_selected: bool,
    min_mols: int = 1,
    empty_message: str | None = None,
    too_few_message: str | None = None,
) -> list[StructurePayload] | None:
    """Validate scope and snapshot structure payloads without RDKit hydrate.

    Returns ``None`` after informing the user when the job should not start.
    """
    if abort_if_only_selected_but_empty(app, only_selected, app._selected_oids_set(), tool_label):
        return None
    reader, allowed = _reader_for_scope(app, only_selected=only_selected)
    plan = plan_scoped_structure_records(
        reader,
        structure_source,
        allowed_oids=allowed,
        min_count=min_mols,
    )
    if plan.is_ready:
        return list(plan.payloads)
    if plan.blocked_by is ScopeBlocker.TOO_FEW_STRUCTURES:
        message = too_few_message or (
            f"Need at least {int(plan.min_count)} row(s) with valid structures in this scope."
        )
    else:
        message = empty_message or (
            "No valid structures were found for the selected source and scope."
        )
    QMessageBox.information(app, tool_label, message)
    return None


def prepare_scoped_activity_mol_records(
    app: Any,
    *,
    tool_label: str,
    structure_source: str,
    activity_column: str,
    only_selected: bool,
    min_records: int = 2,
) -> list[tuple[int, Chem.Mol, float]] | None:
    """Validate scope + activity column and build MMP/SALI worker records.

    Hydrates on the caller thread. Queued tools should use
    :func:`prepare_scoped_activity_payload_records`.
    """
    records = prepare_scoped_activity_payload_records(
        app,
        tool_label=tool_label,
        structure_source=structure_source,
        activity_column=activity_column,
        only_selected=only_selected,
        min_records=min_records,
    )
    if records is None:
        return None
    out: list[tuple[int, Chem.Mol, float]] = []
    for oid, payload, activity in records:
        mol = mol_from_payload(payload)
        if mol is None:
            continue
        out.append((int(oid), mol, float(activity)))
    if len(out) < int(min_records):
        QMessageBox.information(
            app,
            tool_label,
            "Need at least two molecules with both a structure and a numeric activity value.",
        )
        app.status_label.setText("Ready.")
        return None
    return out


def prepare_scoped_activity_payload_records(
    app: Any,
    *,
    tool_label: str,
    structure_source: str,
    activity_column: str,
    only_selected: bool,
    min_records: int = 2,
) -> list[tuple[int, StructurePayload, float]] | None:
    """Snapshot payloads + numeric activity without hydrating RDKit molecules."""
    if abort_if_only_selected_but_empty(app, only_selected, app._selected_oids_set(), tool_label):
        return None
    reader, allowed = _reader_for_scope(app, only_selected=only_selected)
    plan = plan_scoped_activity_records(
        reader,
        structure_source,
        activity_column=activity_column,
        allowed_oids=allowed,
        min_records=min_records,
    )
    if plan.is_ready:
        return [(oid, payload, activity) for oid, payload, activity in plan.records]
    QMessageBox.information(app, tool_label, _activity_block_message(plan))
    if plan.blocked_by in (ScopeBlocker.NO_STRUCTURES, ScopeBlocker.TOO_FEW_ACTIVITY):
        app.status_label.setText("Ready.")
    return None


def _reader_for_scope(
    app: Any, *, only_selected: bool
) -> tuple[WindowTableReader, set[int] | None]:
    """The open table, and the selected oids when the job is limited to them."""
    allowed = set(app._selected_oids_set()) if only_selected else None
    return WindowTableReader(app), allowed


def _activity_block_message(plan: Any) -> str:
    if plan.blocked_by is ScopeBlocker.NO_ACTIVITY_CHOSEN:
        return "Select a numeric activity column."
    if plan.blocked_by is ScopeBlocker.MISSING_ACTIVITY_COLUMN:
        return f"Activity column “{plan.activity_column}” is not in the table."
    if plan.blocked_by is ScopeBlocker.NO_STRUCTURES:
        return "No valid structures were found for the selected source and scope."
    return "Need at least two molecules with both a structure and a numeric activity value."


def prepare_queue_progress(app: Any, tool_label: str, n_items: int) -> tuple[str, Any]:
    """Allocate a job id, begin its progress slot, and return ``(job_id, bound_state)``."""
    job_id = str(uuid.uuid4())[:8]
    ps = app._tool_progress_state
    bind = getattr(ps, "bind", None)
    if callable(bind):
        ps = bind(job_id)
    app._begin_tool_progress(tool_label, int(n_items), job_id=job_id)
    return job_id, ps


def enqueue_process_queue_job(
    app: Any,
    tool_label: str,
    n_items: int,
    factory: Callable,
    *,
    queue_label: str | None = None,
) -> Any:
    """Begin a named progress slot, then enqueue a process-queue worker factory.

    ``factory`` is ``(cancel_event, progress_state) -> QRunnable``. Returns the job
    id shared by the Log row and ``ToolProgressState`` slot.
    """
    label = queue_label or f"{tool_label} ({int(n_items)} rows)"
    job_id, ps = prepare_queue_progress(app, tool_label, int(n_items))
    return app.process_queue.enqueue(
        label,
        lambda ev, _f=factory, _ps=ps: _f(ev, _ps),
        job_id=job_id,
    )


def enqueue_fast_process_queue_job(
    app: Any,
    tool_label: str,
    n_items: int,
    factory: Callable,
    *,
    queue_label: str | None = None,
) -> Any:
    """Like :func:`enqueue_process_queue_job` but uses the fast process-queue lane."""
    label = queue_label or f"{tool_label} ({int(n_items)} rows)"
    job_id, ps = prepare_queue_progress(app, tool_label, int(n_items))
    return app.process_queue.enqueue_fast(
        label,
        lambda ev, _f=factory, _ps=ps: _f(ev, _ps),
        job_id=job_id,
    )


def start_scoped_structure_job(
    app: Any,
    *,
    tool_label: str,
    structure_source: str,
    only_selected: bool,
    make_worker: WorkerFactory,
    min_mols: int = 1,
    queue_label: str | None = None,
    empty_message: str | None = None,
    too_few_message: str | None = None,
) -> Any | None:
    """Snapshot scoped payloads and enqueue ``make_worker(mols, …)``.

    ``make_worker`` receives hydrated ``(mols, *, cancel_event, signals, progress_state)``
    on the process-queue thread. Returns the queue job id, or ``None`` when the job
    did not start.
    """
    payloads = prepare_scoped_structure_payloads(
        app,
        tool_label=tool_label,
        structure_source=structure_source,
        only_selected=only_selected,
        min_mols=min_mols,
        empty_message=empty_message,
        too_few_message=too_few_message,
    )
    if not payloads:
        return None
    job_id, ps = prepare_queue_progress(app, tool_label, len(payloads))
    label = queue_label or f"{tool_label} ({len(payloads)} rows)"
    return app.process_queue.enqueue(
        label,
        lambda ev, rows=payloads, sigs=app.signals, prog=ps: make_worker(
            oid_mol_rows_from_payloads(rows),
            cancel_event=ev,
            signals=sigs,
            progress_state=prog,
        ),
        job_id=job_id,
    )


def start_scoped_activity_job(
    app: Any,
    *,
    tool_label: str,
    structure_source: str,
    activity_column: str,
    only_selected: bool,
    make_worker: WorkerFactory,
    min_records: int = 2,
) -> bool:
    """Snapshot scoped payloads and enqueue ``make_worker(records, …)``.

    ``make_worker`` receives hydrated ``(records, *, cancel_event, signals, progress_state)``
    on the process-queue thread.
    """
    records = prepare_scoped_activity_payload_records(
        app,
        tool_label=tool_label,
        structure_source=structure_source,
        activity_column=activity_column,
        only_selected=only_selected,
        min_records=min_records,
    )
    if not records:
        return False
    job_id, ps = prepare_queue_progress(app, tool_label, len(records))

    def _hydrate_records(rec):
        out = []
        for oid, payload, activity in rec:
            mol = mol_from_payload(payload)
            if mol is None:
                continue
            out.append((int(oid), mol, float(activity)))
        return out

    app.process_queue.enqueue(
        f"{tool_label} ({len(records)} rows)",
        lambda ev, rec=records, sigs=app.signals, prog=ps: make_worker(
            _hydrate_records(rec),
            cancel_event=ev,
            signals=sigs,
            progress_state=prog,
        ),
        job_id=job_id,
    )
    return True


def finish_analysis_pairs(
    app: Any,
    tool_label: str,
    pairs: Sequence[Any] | None,
    *,
    empty_message: str,
    job_id: str | None = None,
) -> list[Any] | None:
    """Finish tool progress; return pairs list or ``None`` when empty (after UI notice)."""
    app._finish_tool_progress(tool_label, job_id=job_id)
    out = list(pairs or [])
    if not out:
        app.status_label.setText("Ready.")
        QMessageBox.information(app, tool_label, empty_message)
        return None
    return out


def report_analysis_failure(
    app: Any,
    tool_label: str,
    message: str,
    *,
    fallback: str,
    job_id: str | None = None,
) -> None:
    """Clear progress and show a warning for a failed analysis job."""
    app._clear_tool_progress(job_id=job_id)
    app.status_label.setText("Ready.")
    QMessageBox.warning(app, tool_label, message or fallback)


def report_cancellable_job_failure(
    app: Any,
    tool_label: str,
    message: str,
    *,
    progress_label: str,
    failure_fallback: str,
    cancelled_status: str | None = None,
    after_finish: Callable[[], None] | None = None,
    job_id: str | None = None,
) -> None:
    """Finish progress for cancellable queue jobs (Cluster, Diverse subset, predictors).

    Cancelled jobs update the status bar only; other failures show a warning.
    """
    app._finish_tool_progress(progress_label, job_id=job_id)
    if after_finish is not None:
        after_finish()
    if message == "Cancelled.":
        notice = getattr(app, "_consume_partial_results_notice", None)
        text = cancelled_status
        if text is None and callable(notice):
            text = notice() or "Cancelled."
        if text is None:
            text = "Cancelled."
        app.status_label.setText(text)
        return
    app.status_label.setText("Ready.")
    QMessageBox.warning(app, tool_label, message or failure_fallback)
