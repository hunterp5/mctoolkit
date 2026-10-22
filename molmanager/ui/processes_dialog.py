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

"""Modeless dialog listing queued and running background tool jobs plus the session log."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .app_log_dialog import SessionLogPanel
from .qt_widget_utils import make_window_resizable

if TYPE_CHECKING:
    from .main_window import ChemistryWorkspaceWindow


class ProcessesDialog(QDialog):
    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self._app: Any = parent
        self.setWindowTitle("Log")
        self.resize(820, 680)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        jobs = QWidget()
        jobs_ly = QVBoxLayout(jobs)
        jobs_ly.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Status", "Progress", "Elapsed", "Job ID", "Title"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        jobs_ly.addWidget(self._table, 1)

        self._log = SessionLogPanel(embed_filters=False)
        splitter.addWidget(jobs)
        splitter.addWidget(self._log)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([240, 420])
        root.addWidget(splitter, 1)

        row = QHBoxLayout()
        self._btn_cancel = QPushButton("Cancel Job")
        self._btn_cancel.setToolTip(
            "Apply to the selected row: stop a running job (cooperative), end Render 2D, "
            "stop Gnina docking, or remove a queued job from the line without running it."
        )
        self._btn_clear = QPushButton("Clear Queue")
        self._btn_clear.setToolTip(
            "Remove all jobs waiting to run (does not stop the current job)."
        )
        row.addWidget(self._btn_cancel)
        row.addWidget(self._btn_clear)
        row.addWidget(self._log.filter_bar(), 1)
        root.addLayout(row)

        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_clear.clicked.connect(self._on_clear_queue)
        self._table.itemSelectionChanged.connect(self._update_cancel_enabled)

        hub = getattr(self._app, "background_activity", None)
        if hub is not None:
            hub.changed.connect(self._reload)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._reload)
        self._timer.start()

        self._reload()
        make_window_resizable(self)

    def _selection_meta(self) -> dict | None:
        sel = self._table.selectedIndexes()
        if not sel:
            return None
        r = sel[0].row()
        it = self._table.item(r, 0)
        if it is None:
            return None
        m = it.data(Qt.UserRole)
        return m if isinstance(m, dict) else None

    def _update_cancel_enabled(self) -> None:
        m = self._selection_meta()
        if m is None:
            self._btn_cancel.setEnabled(False)
            return
        if m.get("kind") == "render2d":
            hub = getattr(self._app, "background_activity", None)
            self._btn_cancel.setEnabled(
                bool(hub.render2d_batch_active()) if hub is not None else False
            )
        elif m.get("kind") in {"gnina", "smina"}:
            hub = getattr(self._app, "background_activity", None)
            active = False
            if hub is not None:
                probe = getattr(hub, "gnina_dock_active", None) or getattr(
                    hub, "smina_dock_active", None
                )
                active = bool(probe()) if callable(probe) else False
            self._btn_cancel.setEnabled(active)
        elif m.get("kind") == "pq_running":
            hub = getattr(self._app, "background_activity", None)
            if hub is not None and hub.render2d_batch_active() and hub._render2d_on_process_queue():
                self._btn_cancel.setEnabled(True)
            else:
                self._btn_cancel.setEnabled(bool(m.get("cancellable")))
        elif m.get("kind") == "pq_fast_running":
            self._btn_cancel.setEnabled(bool(m.get("cancellable", True)))
        elif m.get("kind") == "pq_queued":
            self._btn_cancel.setEnabled(True)
        elif m.get("kind") == "background":
            self._btn_cancel.setEnabled(bool(m.get("cancellable")))
        else:
            self._btn_cancel.setEnabled(False)

    def _reload(self) -> None:
        hub = getattr(self._app, "background_activity", None)
        if hub is None:
            return
        prev = self._selection_meta()
        rows, metas = hub.processes_view_rows()

        self._table.setRowCount(len(rows))
        for i, ((st, jid, title), meta) in enumerate(zip(rows, metas)):
            it0 = QTableWidgetItem(st)
            it0.setData(Qt.UserRole, meta)
            self._table.setItem(i, 0, it0)
            progress = ""
            if isinstance(meta, dict):
                progress = str(meta.get("progress") or "")
            self._table.setItem(i, 1, QTableWidgetItem(progress))
            self._table.setItem(i, 2, QTableWidgetItem(self._format_elapsed(meta)))
            self._table.setItem(i, 3, QTableWidgetItem(jid))
            self._table.setItem(i, 4, QTableWidgetItem(title))

        if prev:
            for i in range(self._table.rowCount()):
                it0 = self._table.item(i, 0)
                cur = it0.data(Qt.UserRole) if it0 else None
                if (
                    isinstance(cur, dict)
                    and isinstance(prev, dict)
                    and self._meta_matches_row(prev, cur)
                ):
                    self._table.selectRow(i)
                    break

        self._update_cancel_enabled()

    @staticmethod
    def _meta_matches_row(prev: dict, cur: dict) -> bool:
        if prev.get("kind") != cur.get("kind"):
            return False
        if prev.get("kind") == "render2d":
            return True
        if prev.get("kind") in {"gnina", "smina"}:
            return True
        return prev.get("job_id") == cur.get("job_id")

    @staticmethod
    def _format_elapsed(meta: dict) -> str:
        started_at = meta.get("started_at")
        enqueued_at = meta.get("enqueued_at")
        base = started_at if isinstance(started_at, (int, float)) else enqueued_at
        if not isinstance(base, (int, float)):
            return ""
        s = max(0, int(time.monotonic() - float(base)))
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"

    def _on_cancel(self) -> None:
        m = self._selection_meta()
        hub = getattr(self._app, "background_activity", None)
        if hub is None:
            return
        dialog_info, status = hub.try_cancel_row(m)
        if dialog_info is not None:
            QMessageBox.information(self, dialog_info[0], dialog_info[1])
        elif status:
            self._app.status_label.setText(status)
        self._reload()

    def _on_clear_queue(self) -> None:
        hub = getattr(self._app, "background_activity", None)
        if hub is None:
            return
        n = hub.clear_queued_jobs()
        if n:
            QMessageBox.information(self, "Clear queue", f"Removed {n} queued job(s).")
        else:
            QMessageBox.information(self, "Clear queue", "The queue was already empty.")
        self._reload()
