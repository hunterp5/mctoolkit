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

"""Screen packed conformation ensembles against a 3D pharmacophore JSON."""

from __future__ import annotations

import uuid
from pathlib import Path

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...conformers.conformer_column_codec import is_packed_ensemble_header
from ...platform_support.config import load_config
from ...protein.pharmacophore import PHARMACOPHORE_FILE_FILTER, load_pharmacophore
from ...protein.pharmacophore_screen import (
    DEFAULT_SLACK_ANGSTROM,
    output_column_names,
    screening_features,
)
from ...workers.pharmacophore_screen import PharmacophoreScreenWorker
from ...workers.signals import PharmacophoreScreenSignals
from ..chunked_table_write import ChunkedTableWriter
from ..qt_widget_utils import boxed_form, make_window_minimizable
from ..analysis_job_support import enqueue_fast_process_queue_job
from .scope import selection_scope_checked


def _ensemble_column_headers(app) -> list[str]:
    if app is None:
        return []
    headers = [str(h).strip() for h in (getattr(app, "headers", None) or []) if str(h).strip()]
    names: list[str] = []
    for header in headers:
        if is_packed_ensemble_header(header):
            names.append(header)
        sidecar = getattr(app, "_confs_blocks_sidecar", None)
        if sidecar is None:
            sidecar = {}
    for key in sidecar:
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        col = str(key[1] or "").strip()
        if col and col not in names and col in headers:
            names.append(col)
    return names


class PharmacophoreScreenDialog(QDialog):
    """Match table conformation ensembles to a crystal-ligand pharmacophore."""

    def __init__(self, parent=None, *, pharmacophore_path: str = "") -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Screen Pharmacophore")
        self.setMinimumWidth(460)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._compare_oids: set[int] = set()
        self._pending_columns: tuple[str, str, str, str] = output_column_names("pharma")
        self._ensemble_db: str | None = None
        self._ensemble_column: str | None = None
        self._writer: ChunkedTableWriter | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        query, form = boxed_form("Query")

        self.edit_pharmacophore = QLineEdit()
        self.edit_pharmacophore.setPlaceholderText("pharmacophore.json")
        self.edit_pharmacophore.setToolTip(
            "MolManager pharmacophore JSON from Protein Viewer. Exclusion volumes are "
            "ignored; matching uses RDKit feature types and pairwise distances so table "
            "ensembles need not share the protein coordinate frame."
        )
        if pharmacophore_path:
            self.edit_pharmacophore.setText(pharmacophore_path)
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(76)
        btn_browse.clicked.connect(self._browse_pharmacophore)
        ph_row = QHBoxLayout()
        ph_row.setContentsMargins(0, 0, 0, 0)
        ph_row.setSpacing(4)
        ph_row.addWidget(self.edit_pharmacophore, 1)
        ph_row.addWidget(btn_browse)
        ph_wrap = QWidget()
        ph_wrap.setLayout(ph_row)
        form.addRow("Pharmacophore:", ph_wrap)

        self.combo_ensemble = QComboBox()
        self.combo_ensemble.setToolTip(
            "Packed ensemble column (confs, superpose, poses). Each conformer is scored; "
            "the best match is written per row."
        )
        form.addRow("Ensembles:", self.combo_ensemble)
        self._refresh_ensemble_columns()

        self.spin_slack = QDoubleSpinBox()
        self.spin_slack.setRange(0.1, 10.0)
        self.spin_slack.setDecimals(2)
        self.spin_slack.setSingleStep(0.1)
        self.spin_slack.setValue(DEFAULT_SLACK_ANGSTROM)
        self.spin_slack.setSuffix(" Å")
        self.spin_slack.setToolTip(
            "Allowed difference between query and ligand pairwise feature distances."
        )
        form.addRow("Distance slack:", self.spin_slack)

        self.chk_require_all = QCheckBox("Require all features")
        self.chk_require_all.setChecked(True)
        self.chk_require_all.setToolTip(
            "Every enabled non-Exclusion site must map onto a same-type ligand feature. "
            "Uncheck to accept a minimum number of matched sites."
        )
        self.spin_min = QSpinBox()
        self.spin_min.setRange(1, 32)
        self.spin_min.setValue(3)
        self.spin_min.setEnabled(False)
        self.spin_min.setToolTip("Minimum matched query features when not requiring all.")
        min_row = QHBoxLayout()
        min_row.setContentsMargins(0, 0, 0, 0)
        min_row.setSpacing(8)
        min_row.addWidget(self.chk_require_all)
        min_row.addWidget(QLabel("Min:"))
        min_row.addWidget(self.spin_min)
        min_row.addStretch()
        min_wrap = QWidget()
        min_wrap.setLayout(min_row)
        form.addRow("", min_wrap)
        self.chk_require_all.toggled.connect(self.spin_min.setDisabled)
        root.addWidget(query)

        output, out_form = boxed_form("Output")
        self.edit_prefix = QLineEdit("pharma")
        self.edit_prefix.setToolTip("Output columns are {prefix}Match, Score, RMSD, and Conf.")
        out_form.addRow("Column prefix:", self.edit_prefix)

        self.only_selected_cb = QCheckBox("Only selected rows")
        self._only_selected_scope_prefix = "Only selected rows"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        out_form.addRow("", self.only_selected_cb)

        self.chk_select_hits = QCheckBox("Select Hits in Table")
        self.chk_select_hits.setChecked(True)
        self.chk_select_hits.setToolTip(
            "After the screen finishes, select every row that matched the pharmacophore."
        )
        out_form.addRow("", self.chk_select_hits)
        root.addWidget(output)
        self._select_hits = True

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Screen")
        self.run_btn.clicked.connect(self.run_screen)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._signals = PharmacophoreScreenSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        make_window_minimizable(self)

    def set_pharmacophore_path(self, path: str) -> None:
        text = (path or "").strip()
        if text:
            self.edit_pharmacophore.setText(text)

    def _browse_pharmacophore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pharmacophore",
            self.edit_pharmacophore.text(),
            PHARMACOPHORE_FILE_FILTER,
        )
        if path:
            self.edit_pharmacophore.setText(path)

    def _refresh_ensemble_columns(self) -> None:
        current = (self.combo_ensemble.currentText() or "").strip()
        self.combo_ensemble.blockSignals(True)
        self.combo_ensemble.clear()
        names = _ensemble_column_headers(self.parent_app)
        for name in names:
            self.combo_ensemble.addItem(name)
        idx = self.combo_ensemble.findText(current)
        if idx < 0:
            idx = self.combo_ensemble.findText("confs")
        if idx >= 0:
            self.combo_ensemble.setCurrentIndex(idx)
        elif names:
            self.combo_ensemble.setCurrentIndex(0)
        self.combo_ensemble.blockSignals(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_ensemble_columns()

    def _pending_unique_columns(self) -> tuple[str, str, str, str]:
        prefix = (self.edit_prefix.text() or "").strip() or "pharma"
        names = []
        taken = list(getattr(self.parent_app, "headers", []) or [])
        for raw in output_column_names(prefix):
            name = raw
            if name in taken:
                cnt = 1
                while f"{raw} ({cnt})" in taken:
                    cnt += 1
                name = f"{raw} ({cnt})"
            taken.append(name)
            names.append(name)
        return names[0], names[1], names[2], names[3]

    def _compare_oids_in_scope(self, only_selected: bool) -> set[int]:
        allowed = self.parent_app._selected_oids_set() if only_selected else None
        oids: set[int] = set()
        model = self.parent_app._table_model
        for row in range(model.rowCount()):
            oid = model.row_oid(row)
            if allowed is not None and oid not in allowed:
                continue
            oids.add(oid)
        return oids

    def _collect_ensemble_mols(self, column: str, oids: set[int]) -> list:
        from ...storage import EnsembleStore, ensemble_db_path
        from ...ui.main_window.conformer_writeback import mol_for_ensemble_column

        app = self.parent_app
        model = getattr(app, "_table_model", None)
        if model is None:
            return []
        store = getattr(app, "_confs_blocks_sidecar", None)
        db = ensemble_db_path(app)
        keys: list[tuple[int, None]] = []
        mols: list[tuple[int, object]] = []
        for row in range(model.rowCount()):
            try:
                oid = int(model.row_oid(row))
            except Exception:
                continue
            if oid not in oids:
                continue
            if isinstance(store, EnsembleStore) and (oid, column) in store:
                keys.append((oid, None))
                continue
            packed = mol_for_ensemble_column(app, oid, column, min_conformers=1)
            if packed is not None:
                mols.append((oid, packed))
        if keys and not mols and db is not None:
            self._ensemble_db = str(db)
            self._ensemble_column = column
            return keys
        self._ensemble_db = None
        self._ensemble_column = None
        for oid, _none in keys:
            packed = mol_for_ensemble_column(app, oid, column, min_conformers=1)
            if packed is not None:
                mols.append((oid, packed))
        return mols

    def run_screen(self) -> None:
        app = self.parent_app
        if app is None:
            return
        path = (self.edit_pharmacophore.text() or "").strip()
        if not path or not Path(path).is_file():
            app.status_label.setText("Pharmacophore screen: choose a pharmacophore JSON file.")
            return
        try:
            pharma = load_pharmacophore(path)
        except ValueError as exc:
            app.status_label.setText(f"Pharmacophore screen: {exc}")
            return
        query_feats = screening_features(pharma)
        if not query_feats:
            app.status_label.setText(
                "Pharmacophore screen: the file has no enabled (non-Exclusion) features."
            )
            return
        column = (self.combo_ensemble.currentText() or "").strip()
        if not column:
            app.status_label.setText(
                "Pharmacophore screen: the table has no packed ensemble column "
                "(confs, superpose, or poses)."
            )
            return
        only_sel = selection_scope_checked(self)
        if only_sel and not app._selected_oids_set():
            app.status_label.setText(
                "Pharmacophore screen: “Only selected rows” is checked but nothing is selected."
            )
            return
        compare_oids = self._compare_oids_in_scope(only_sel)
        if not compare_oids:
            app.status_label.setText("Pharmacophore screen: no rows in scope.")
            return
        targets = self._collect_ensemble_mols(column, compare_oids)
        if not targets:
            app.status_label.setText(
                f"Pharmacophore screen: no 3D ensembles in “{column}” for the current scope."
            )
            return
        min_matched = None
        if not self.chk_require_all.isChecked():
            min_matched = int(self.spin_min.value())
        self._compare_oids = compare_oids
        self._pending_columns = self._pending_unique_columns()
        self._select_hits = self.chk_select_hits.isChecked()
        self.run_btn.setEnabled(False)
        query = pharma.to_dict()
        slack = float(self.spin_slack.value())
        db = getattr(self, "_ensemble_db", None)
        col = getattr(self, "_ensemble_column", None)
        enqueue_fast_process_queue_job(
            app,
            "Pharmacophore screen",
            max(1, len(targets)),
            lambda ev, ps, q=query, t=targets, s=slack, m=min_matched, sig=self._signals, edb=db, ecol=col: (
                PharmacophoreScreenWorker(
                    q,
                    t,
                    sig,
                    slack=s,
                    min_matched=m,
                    cancel_event=ev,
                    progress_state=ps,
                    ensemble_db=edb,
                    ensemble_column=ecol,
                )
            ),
            queue_label="Pharmacophore screen",
        )
        self.close()

    def _result_column_maps(self, rows) -> tuple[tuple[dict[int, str], ...], int, list[int]]:
        """Turn worker rows into one oid->text map per result column.

        Rows in scope that the worker never reported (and rows it could not
        screen) are filled with ``N/A`` so the columns stay aligned with scope.
        """
        match_map: dict[int, str] = {}
        score_map: dict[int, str] = {}
        rmsd_map: dict[int, str] = {}
        conf_map: dict[int, str] = {}
        maps = (match_map, score_map, rmsd_map, conf_map)
        n_hit = 0
        hit_oids: list[int] = []
        found = set()
        for oid, matched, score, rmsd, conf_id in rows or []:
            found.add(int(oid))
            if matched is None:
                for oid_map in maps:
                    oid_map[int(oid)] = "N/A"
                continue
            if matched:
                n_hit += 1
                hit_oids.append(int(oid))
            match_map[int(oid)] = "1" if matched else "0"
            score_map[int(oid)] = f"{float(score):.4f}"
            rmsd_map[int(oid)] = "" if rmsd is None else f"{float(rmsd):.3f}"
            conf_map[int(oid)] = "" if conf_id is None else str(int(conf_id))
        for oid in self._compare_oids:
            if oid in found:
                continue
            for oid_map in maps:
                oid_map[oid] = "N/A"
        return maps, n_hit, hit_oids

    def _write_columns(self, rows) -> None:
        app = self.parent_app
        maps, n_hit, hit_oids = self._result_column_maps(rows)
        names = list(self._pending_columns)
        model = app._table_model
        for name in names:
            app.headers.append(name)
        model.insert_columns_at(model.columnCount(), names, None)

        n_rows = model.rowCount()
        n_scope = len(self._compare_oids)
        cfg = load_config()
        chunked = n_rows >= max(500, int(cfg.tool_table_chunk_rows))

        def write_chunk(start: int, end: int, is_last: bool) -> None:
            for name, oid_map in zip(names, maps):
                model.fill_column_from_oid_map(
                    name,
                    oid_map,
                    default="",
                    start_row=start,
                    end_row=end,
                    emit=True,
                    rebuild_color=is_last,
                )

        def on_done() -> None:
            app._sync_global_bounds_for_headers(names, refresh_filters=True)
            if chunked:
                app._finish_tool_progress(
                    "Writing results", status_message=None, job_id=write_job_id
                )
            self._finish_screen_results(n_hit, n_scope, hit_oids)

        if self._writer is not None:
            self._writer.cancel()
        write_job_id = str(uuid.uuid4())[:8] if chunked else None
        self._writer = ChunkedTableWriter(
            table=app.table,
            total=n_rows,
            chunk=max(250, int(cfg.ingest_gui_chunk_size)) if chunked else max(1, n_rows),
            write_chunk=write_chunk,
            on_progress=(
                (
                    lambda done, total, jid=write_job_id: app._tool_progress_state.update(
                        "Writing results…", done, total, job_id=jid
                    )
                )
                if chunked
                else None
            ),
            on_done=on_done,
            should_continue=lambda: self.parent_app is not None,
        )
        if chunked:
            app._begin_tool_progress("Writing results", n_rows, job_id=write_job_id)
            self._writer.start()
        else:
            self._writer.run_now()

    def _finish_screen_results(self, n_hit: int, n_scope: int, hit_oids: list[int]) -> None:
        app = self.parent_app
        if app is None:
            return
        # Select after column insert — inserting columns clears Qt selection.
        if getattr(self, "_select_hits", False) and hit_oids:
            app.select_table_oids(hit_oids, extra_status="Pharmacophore hits")
        app.status_label.setText(
            f"Pharmacophore screen: {n_hit} hit(s) of {n_scope} row(s) in scope."
        )

    def _on_finished(self, rows) -> None:
        self.run_btn.setEnabled(True)
        self.parent_app._finish_tool_progress("Pharmacophore screen")
        if not self._pending_columns:
            return
        self._write_columns(rows)

    def _on_failed(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.parent_app._finish_tool_progress("Pharmacophore screen")
        self.parent_app.status_label.setText(
            f"Pharmacophore screen failed: {msg or 'Computation failed.'}"
        )
