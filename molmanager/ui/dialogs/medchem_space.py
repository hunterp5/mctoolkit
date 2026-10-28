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

"""BOILED-Egg, golden-triangle, and LipE plots (Data menu)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Callable, Literal

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..dockable_plot import (
    handle_floating_plot_close_event,
    hide_plot_options_dialog,
    make_plot_options_dialog,
    show_plot_options_dialog,
    style_plot_footer_text_button,
)
from ..background_jobs import register_background_job
from ...platform_support.config import load_config
from ...platform_support.session_log import session_log_buffer
from ...plotting.plot_marker_color import color_values_are_numeric, normalize_size_column
from ...chem.molecule_conversion import mol_to_canonical_smiles
from ...analysis.medchem_space import (
    MedChemRowSnapshot,
    MedChemSpaceBuildResult,
    MedChemSpaceDataset,
    MedChemSpacePoint,
    medchem_plot_max_points,
    oids_in_egg_gia,
    oids_in_egg_yolk,
    oids_in_golden_triangle_region,
    oids_with_lipe_at_least,
    medchem_activity_column_problem,
    medchem_descriptor_columns,
    medchem_export_headers,
    medchem_snapshot_from_cells,
    medchem_structure_text,
    plan_medchem_plot_start,
    prefer_pactivity_column,
    required_descriptor_columns_ok,
)
from ...workers.medchem_space_worker import MedChemSpaceSignals, MedChemSpaceWorker
from ..table_dataframe import numeric_subset, table_to_dataframe
from ..chunked_table_write import ChunkedTableWriter
from ..medchem_space_plot import (
    _MARKER_OPACITY,
    build_boiled_egg_figure,
    build_golden_triangle_figure,
    build_lipe_figure,
)
from ..plotly_interactive_view import PlotlyInteractiveView
from ..plot_table_sync import retained_snapshot_oids
from ..qt_widget_utils import make_window_resizable
from ..result_plot_panel import DockableResultPlotPanel
from .scope import selection_scope_checked

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    _HAS_WEB = True
except ImportError:
    _HAS_WEB = False


MedChemPlotKind = Literal["boiled_egg", "golden_triangle", "lipe"]


class MedChemPlotPanel(DockableResultPlotPanel):
    """BOILED-Egg, golden-triangle, or LipE controls + plot (dialog or docked)."""

    MEDCHEM_SESSION_KIND = "medchem_space"
    owns_docked_plot_actions = True

    def __init__(
        self,
        parent_app: ChemistryWorkspaceWindow | None,
        *,
        plot_kind: MedChemPlotKind,
        window_title: str,
        session_restore: bool = False,
    ):
        n_sel = len(parent_app._selected_logical_rows()) if parent_app is not None else 0
        self._plot_kind = plot_kind
        self._have_selection = n_sel > 0
        self._full_dataset: MedChemSpaceDataset | None = None
        self._plot_dataset: MedChemSpaceDataset | None = None
        self._job_running = False
        self._snapshot_collect_gen = 0
        self._snapshot_collect_ctx: dict | None = None
        self._table_writer: ChunkedTableWriter | None = None
        lipe = plot_kind == "lipe"
        super().__init__(
            parent_app,
            window_title=window_title,
            floating_dialog_cls=MedChemSpaceDialog,
            parent=None,
            opts_title=window_title if lipe else f"{window_title} — Plot Options",
            opts_tooltip=(
                "Choose a pActivity column, then Run."
                if lipe
                else "Configure structure source, color, and On Hover."
            ),
            pair_encoding=False,
            defer_initial_reload=True,
            default_marker_opacity=_MARKER_OPACITY,
        )
        self._medchem_signals = MedChemSpaceSignals(self)
        self._medchem_signals.finished.connect(self._on_build_finished, Qt.QueuedConnection)
        self._medchem_signals.failed.connect(self._on_build_failed, Qt.QueuedConnection)

        if _HAS_WEB and parent_app is not None:
            self._plot_view = PlotlyInteractiveView(parent_app, self)
            self._plot_view.setMinimumHeight(420)
            self._root.addWidget(self._plot_view, 1)
            self._plot_placeholder = None
        else:
            self._plot_view = None
            self._plot_placeholder = QLabel(
                "Install PyQtWebEngine to show the interactive plot in this window."
            )
            self._plot_placeholder.setWordWrap(True)
            self._plot_placeholder.setAlignment(Qt.AlignCenter)
            self._root.addWidget(self._plot_placeholder, 1)

        extras = self._extra_opts_layout
        options_gb = QGroupBox("Options")
        options_ly = QVBoxLayout(options_gb)
        options_ly.setSpacing(6)

        self.activity_combo: QComboBox | None = None
        self.run_btn: QPushButton | None = None
        if plot_kind == "lipe":
            activity_row = QHBoxLayout()
            activity_row.addWidget(QLabel("pActivity from:"))
            self.activity_combo = QComboBox()
            self.activity_combo.setToolTip(
                "pIC50, pKi, or pEC50 column. LipE is that value minus LogP."
            )
            activity_row.addWidget(self.activity_combo, 1)
            options_ly.addLayout(activity_row)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        self.only_selected_cb.stateChanged.connect(self._on_scope_changed)
        options_ly.addWidget(self.only_selected_cb)

        struct_row = QHBoxLayout()
        struct_row.addWidget(QLabel("Structure from:"))
        self.struct_src_combo = QComboBox()
        struct_row.addWidget(self.struct_src_combo, 1)
        options_ly.addLayout(struct_row)
        if plot_kind == "lipe":
            run_row = QHBoxLayout()
            run_row.setContentsMargins(0, 10, 0, 6)
            run_row.addStretch()
            self.run_btn = QPushButton("Run")
            self.run_btn.setMinimumWidth(160)
            self.run_btn.setStyleSheet("QPushButton { padding: 8px 28px; }")
            self.run_btn.clicked.connect(self._on_lipe_run)
            run_row.addWidget(self.run_btn)
            run_row.addStretch()
            options_ly.addLayout(run_row)
        extras.addWidget(options_gb)

        foot = self._footer_bar.layout()
        clear_idx = foot.indexOf(self._clear_sel_btn)
        insert_at = clear_idx + 1 if clear_idx >= 0 else 2
        if plot_kind == "golden_triangle":
            self.select_region_btn = QPushButton("Triangle")
            self.select_region_btn.setToolTip("Select compounds inside the golden triangle.")
            self.select_region_btn.clicked.connect(self._on_select_in_triangle)
            style_plot_footer_text_button(self.select_region_btn)
            foot.insertWidget(insert_at, self.select_region_btn)
        elif plot_kind == "lipe":
            self.select_region_btn = QPushButton("LipE ≥ 5")
            self.select_region_btn.setToolTip(
                "Select compounds with lipophilic efficiency of at least 5."
            )
            self.select_region_btn.clicked.connect(self._on_select_lipe)
            style_plot_footer_text_button(self.select_region_btn)
            foot.insertWidget(insert_at, self.select_region_btn)
        else:
            self.select_egg_btn = QPushButton("Egg")
            self.select_egg_btn.setToolTip("Select compounds inside the boiled egg.")
            self.select_egg_btn.clicked.connect(self._on_select_in_egg)
            self.select_yolk_btn = QPushButton("Yolk")
            self.select_yolk_btn.setToolTip("Select compounds inside the egg yolk.")
            self.select_yolk_btn.clicked.connect(self._on_select_in_yolk)
            style_plot_footer_text_button(self.select_egg_btn)
            style_plot_footer_text_button(self.select_yolk_btn)
            foot.insertWidget(insert_at, self.select_egg_btn)
            foot.insertWidget(insert_at + 1, self.select_yolk_btn)

        self._refresh_structure_sources()
        self._reload_color_columns()
        self._update_spectrum_controls()
        self._update_size_controls()
        if plot_kind == "lipe":
            self._install_lipe_appearance_dialog()
        self._finish_layout()
        self.setMinimumWidth(self.embedded_minimum_width())
        if not session_restore and plot_kind != "lipe":
            self._set_medchem_status(f"{self._window_title}: preparing plot…")
            QTimer.singleShot(0, self._start_refresh_job)

    def _medchem_dataset_to_dict(self, ds: MedChemSpaceDataset | None) -> dict | None:
        if ds is None:
            return None
        return {
            "points": [asdict(p) for p in ds.points],
            "skipped": ds.skipped,
            "subsample_note": ds.subsample_note,
            "gia_count": ds.gia_count,
            "bbb_count": ds.bbb_count,
            "golden_triangle_count": ds.golden_triangle_count,
        }

    @staticmethod
    def _medchem_dataset_from_dict(raw: object) -> MedChemSpaceDataset | None:
        if not isinstance(raw, dict):
            return None
        points: list[MedChemSpacePoint] = []
        for pt in raw.get("points") or []:
            if isinstance(pt, dict):
                points.append(MedChemSpacePoint(**pt))
        return MedChemSpaceDataset(
            points=tuple(points),
            skipped=int(raw.get("skipped") or 0),
            subsample_note=str(raw.get("subsample_note") or ""),
            gia_count=raw.get("gia_count"),
            bbb_count=raw.get("bbb_count"),
            golden_triangle_count=raw.get("golden_triangle_count"),
        )

    def collect_session_state(self) -> dict:
        return {
            "kind": self.MEDCHEM_SESSION_KIND,
            "plot_kind": self._plot_kind,
            "window_title": self._window_title,
            "only_selected": bool(self.only_selected_cb.isChecked()),
            "struct_src": self.struct_src_combo.currentText(),
            "activity_col": self._activity_column_name() or "",
            **self._collect_encoding_chrome_state(),
            "full_dataset": self._medchem_dataset_to_dict(self._full_dataset),
            "plot_dataset": (
                None
                if self._plot_dataset is None or self._plot_dataset is self._full_dataset
                else self._medchem_dataset_to_dict(self._plot_dataset)
            ),
        }

    def apply_session_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        self._reload_color_columns()
        if "only_selected" in state:
            self.only_selected_cb.setChecked(bool(state.get("only_selected")))
        self._set_combo_text(self.struct_src_combo, state.get("struct_src"))
        if self.activity_combo is not None and state.get("activity_col"):
            self.activity_combo.blockSignals(True)
            self._set_combo_text(self.activity_combo, state.get("activity_col"))
            self.activity_combo.blockSignals(False)
        self._apply_encoding_chrome_state(state)
        self._full_dataset = self._medchem_dataset_from_dict(state.get("full_dataset"))
        self._plot_dataset = self._medchem_dataset_from_dict(state.get("plot_dataset"))
        if self._plot_dataset is None:
            self._plot_dataset = self._full_dataset
        if self._full_dataset is not None:
            total = len(self._full_dataset.points)
            self._log_medchem_summary(
                self._full_dataset.summary_text(plot_kind=self._plot_kind, total_in_scope=total)
            )
        self._update_spectrum_controls()
        self._update_size_controls()
        if self._plot_dataset is not None and self._plot_dataset.points:
            QTimer.singleShot(0, self._push_plot_figure)

    @classmethod
    def from_session_state(cls, parent_app, state: dict | None) -> "MedChemPlotPanel":
        return medchem_plot_panel_from_session(parent_app, state)

    def create_floating_dialog(self, parent_app: ChemistryWorkspaceWindow) -> MedChemSpaceDialog:
        """Re-open this panel in a floating window after undocking from the main table."""
        return MedChemSpaceDialog(
            parent_app,
            plot_kind=self._plot_kind,
            window_title=self._window_title,
            panel=self,
        )

    def _clear_selection(self) -> None:
        """Clear table and plot point selection."""
        if self._plot_view is not None:
            self._plot_view.clear_table_selection(update_plot=True)
        elif self.parent_app is not None:
            self.parent_app.clear_table_selection()

    def _refresh_structure_sources(self) -> None:
        self.struct_src_combo.clear()
        if self.parent_app is None:
            return
        self.struct_src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _reload_color_columns(self) -> None:
        prev = self.color_combo.currentText()
        prev_size = self.size_combo.currentText()
        self.color_combo.blockSignals(True)
        self.size_combo.blockSignals(True)
        try:
            self.color_combo.clear()
            self.color_combo.addItem("(none)")
            self.size_combo.clear()
            self.size_combo.addItem("(none)")
            if self.parent_app is None:
                return
            model = self.parent_app._table_model
            if model.rowCount() > 8000:
                for col in model._sorted_bounds_data_headers():
                    self.color_combo.addItem(col)
                    self.size_combo.addItem(col)
            else:
                only_sel = selection_scope_checked(self)
                df, _rows = table_to_dataframe(
                    self.parent_app, visible_only=False, only_selected=only_sel
                )
                for col in numeric_subset(df, exclude_id=True).columns:
                    self.color_combo.addItem(col)
                    self.size_combo.addItem(col)
            idx = self.color_combo.findText(prev)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)
            sidx = self.size_combo.findText(prev_size)
            if sidx >= 0:
                self.size_combo.setCurrentIndex(sidx)
            self._fill_activity_combo()
        finally:
            self.color_combo.blockSignals(False)
            self.size_combo.blockSignals(False)
        self._reload_hover_columns()

    def _on_scope_changed(self) -> None:
        self._reload_color_columns()

    def _fill_activity_combo(self) -> None:
        combo = self.activity_combo
        if combo is None:
            return
        prev = combo.currentText()
        # Index 0 on the color combo is "(none)". Read that combo, not this one:
        # this combo is still empty here, and itemText past the end is "".
        names = [
            self.color_combo.itemText(i)
            for i in range(1, self.color_combo.count())
            if self.color_combo.itemText(i).strip()
        ]
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(names)
            idx = combo.findText(prev) if prev else -1
            if idx < 0:
                preferred = prefer_pactivity_column(names)
                idx = combo.findText(preferred) if preferred else -1
            if idx >= 0:
                combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    def _activity_column_name(self) -> str | None:
        combo = self.activity_combo
        if combo is None:
            return None
        text = combo.currentText().strip()
        return text or None

    def _install_lipe_appearance_dialog(self) -> None:
        """Keep activity and Run in the setup dialog. Plot Options is appearance only."""
        opts = self._opts_panel.layout()
        opts.removeWidget(self._titles)
        opts.removeWidget(self._markers_group)
        opts.removeWidget(self._hover_controls)

        panel = QWidget()
        body = QVBoxLayout(panel)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        body.addWidget(self._titles)
        body.addWidget(self._markers_group)
        body.addWidget(self._hover_controls)
        body.addStretch(1)
        self._appearance_dialog = make_plot_options_dialog(
            self,
            panel,
            title=f"{self._window_title} — Plot Options",
            min_width=520,
            min_height=280,
        )
        self._opts_btn.setToolTip("Configure titles, Color by, Size by, and On Hover.")

    def _hide_lipe_dialogs(self) -> None:
        hide_plot_options_dialog(getattr(self, "_opts_dialog", None))
        hide_plot_options_dialog(getattr(self, "_appearance_dialog", None))

    def _open_setup_dialog(self) -> None:
        """Activity column, structure source, row scope, and Run."""
        show_plot_options_dialog(self._opts_dialog)

    def _open_plot_options(self) -> None:
        if self._plot_kind == "lipe" and getattr(self, "_appearance_dialog", None) is not None:
            show_plot_options_dialog(self._appearance_dialog)
            return
        show_plot_options_dialog(self._opts_dialog)

    def _ui_parent(self) -> QWidget:
        """Parent for alerts: the open setup or plot-settings dialog, else the plot window."""
        for opts in (
            getattr(self, "_appearance_dialog", None),
            getattr(self, "_opts_dialog", None),
        ):
            try:
                if opts is not None and opts.isVisible():
                    return opts
            except RuntimeError:
                continue
        win = self.window()
        try:
            if win is not None and win.isVisible():
                return win
        except RuntimeError:
            pass
        return self.parent_app or self

    def _plot_window_is_visible(self) -> bool:
        if self._is_docked_in_main_window():
            return True
        win = self.window()
        try:
            return win is not None and win is not self and win.isVisible()
        except RuntimeError:
            return False

    def reveal_plot_window(self) -> None:
        """Show the floating plot host once a LipE figure is ready."""
        self._hide_lipe_dialogs()
        if self._is_docked_in_main_window():
            return
        win = self.window()
        if win is None or win is self:
            return
        try:
            win.show()
            win.raise_()
            win.activateWindow()
        except RuntimeError:
            return

    def present_initial_ui(self) -> None:
        """Open LipE setup until a figure exists; then show the plot window."""
        if self._plot_kind != "lipe":
            return
        if self._full_dataset is not None or self._is_docked_in_main_window():
            self.reveal_plot_window()
            return
        self._open_setup_dialog()

    def _close_options_for_run(self) -> None:
        """Hide setup and plot settings so progress is the main-window status line."""
        self._hide_lipe_dialogs()
        if self._plot_window_is_visible() or self.parent_app is None:
            return
        try:
            self.parent_app.raise_()
            self.parent_app.activateWindow()
        except RuntimeError:
            return

    def _reopen_setup_if_plot_hidden(self) -> None:
        if self._plot_kind != "lipe" or self._plot_window_is_visible():
            return
        self._open_setup_dialog()

    def _on_lipe_run(self) -> None:
        problem = medchem_activity_column_problem(self._plot_kind, self._activity_column_name())
        if problem:
            QMessageBox.information(self._ui_parent(), self._window_title, problem)
            return
        self._close_options_for_run()
        self._on_refresh()
        if not self._job_running:
            self._reopen_setup_if_plot_hidden()

    def _update_spectrum_controls(self) -> None:
        enabled = self.color_combo.currentText() != "(none)"
        self._spectrum_label.setEnabled(enabled)
        self.colorscale_combo.setEnabled(enabled)
        self.invert_spectrum_cb.setEnabled(enabled)
        numeric = False
        if enabled and self._plot_dataset is not None:
            color_col = self.color_combo.currentText()
            vals = self._color_values_for_oids(self._plot_dataset.oids, color_col)
            numeric = color_values_are_numeric(vals)
        self.color_range.set_enabled(enabled and numeric)
        self._update_size_controls()

    def _rebuild_figure(self) -> None:
        self._push_plot_figure()

    def _descriptor_column_names(self) -> tuple[str | None, str | None, str | None, str | None]:
        assert self.parent_app is not None
        return medchem_descriptor_columns(self.parent_app.headers, self._plot_kind)

    def _set_medchem_status(self, message: str) -> None:
        """Show short progress on the main-window status line."""
        app = self.parent_app
        label = getattr(app, "status_label", None) if app is not None else None
        if label is not None:
            label.setText(message)

    def _log_medchem_summary(self, summary: str) -> None:
        """Write the finished plot summary to the in-app log, not the Python shell."""
        text = (summary or "").strip()
        if not text:
            return
        session_log_buffer().add(
            levelno=logging.INFO,
            logger_name="molmanager.ui",
            message=f"{self._window_title}\n{text}",
            source="ui",
        )

    def _set_refresh_ui_busy(self, busy: bool) -> None:
        self._job_running = busy
        for w in (
            self.struct_src_combo,
            self.only_selected_cb,
            getattr(self, "select_region_btn", None),
            getattr(self, "select_egg_btn", None),
            getattr(self, "select_yolk_btn", None),
            self.activity_combo,
            self.run_btn,
            self._clear_sel_btn,
        ):
            if w is not None:
                w.setEnabled(not busy)

    def _structure_text_for_row(self, row: int, src: str) -> str:
        """Read stored cell text only (no RDKit parsing on the UI thread)."""
        assert self.parent_app is not None
        model = self.parent_app._table_model
        display = model.value_for_header(row, src) or ""
        backing = model.backing_value_for_row_header(row, src) or ""
        pixmap = src != "Structure" and bool(model.is_pixmap_data_column(src))
        return medchem_structure_text(source=src, display=display, backing=backing, pixmap=pixmap)

    def _oid_smiles_from_cache(self, snapshots: list[MedChemRowSnapshot]) -> dict[int, str]:
        """SMILES from in-memory mols for rows without structure cell text."""
        app = self.parent_app
        if app is None:
            return {}
        out: dict[int, str] = {}
        for snap in snapshots:
            if (snap.structure_text or "").strip():
                continue
            mol = app.mols.get(int(snap.oid))
            if mol is None:
                continue
            smi = mol_to_canonical_smiles(mol)
            if smi:
                out[int(snap.oid)] = smi
        return out

    def _snapshot_collect_chunk_size(self) -> int:
        cfg = load_config()
        return max(512, int(cfg.tool_table_chunk_rows))

    def _snapshot_scope_row_count(self, scope_rows: list[int] | None) -> int:
        assert self.parent_app is not None
        if scope_rows is not None:
            return len(scope_rows)
        return self.parent_app._table_model.rowCount()

    def _cancel_snapshot_collect(self) -> None:
        self._snapshot_collect_gen += 1
        self._snapshot_collect_ctx = None

    def _snapshot_export_headers(
        self,
        *,
        id_col: str | None,
        tpsa_col: str | None,
        logp_col: str | None,
        mw_col: str | None,
        wlogp_col: str | None,
        activity_col: str | None,
        src: str,
        include_structure: bool,
    ) -> list[str]:
        return medchem_export_headers(
            id_col=id_col,
            tpsa_col=tpsa_col,
            logp_col=logp_col,
            mw_col=mw_col,
            wlogp_col=wlogp_col,
            activity_col=activity_col,
            src=src,
            include_structure=include_structure,
        )

    def _snapshot_from_cells(
        self,
        oid: int,
        cells: dict[str, str],
        *,
        id_col: str | None,
        tpsa_col: str | None,
        logp_col: str | None,
        mw_col: str | None,
        wlogp_col: str | None,
        activity_col: str | None,
        src: str,
    ) -> MedChemRowSnapshot:
        return medchem_snapshot_from_cells(
            oid,
            cells,
            id_col=id_col,
            tpsa_col=tpsa_col,
            logp_col=logp_col,
            mw_col=mw_col,
            wlogp_col=wlogp_col,
            activity_col=activity_col,
            src=src,
        )

    def _snapshot_from_row(
        self,
        row: int,
        *,
        model,
        src: str,
        id_col: str | None,
        tpsa_col: str | None,
        logp_col: str | None,
        mw_col: str | None,
        wlogp_col: str | None,
        activity_col: str | None,
    ) -> MedChemRowSnapshot:
        oid = int(model.row_oid(row))
        cells = {
            header: model.value_for_header(row, header)
            for header in (id_col, tpsa_col, logp_col, mw_col, wlogp_col, activity_col)
            if header
        }
        return medchem_snapshot_from_cells(
            oid,
            cells,
            id_col=id_col,
            tpsa_col=tpsa_col,
            logp_col=logp_col,
            mw_col=mw_col,
            wlogp_col=wlogp_col,
            activity_col=activity_col,
            src=src,
            structure_text=self._structure_text_for_row(row, src),
        )

    def _begin_snapshot_collect(self) -> None:
        if self.parent_app is None:
            return
        app = self.parent_app
        only_sel = selection_scope_checked(self)
        start = plan_medchem_plot_start(
            plot_kind=self._plot_kind,
            headers=app.headers,
            row_count=app._table_model.rowCount(),
            only_selected=only_sel,
            selection_empty=only_sel and not app._selected_oids_set(),
            selected_rows=app._selected_logical_rows() if only_sel else None,
            activity_column=self._activity_column_name(),
        )
        if start.message:
            self._reopen_setup_if_plot_hidden()
            box = QMessageBox.warning if start.warning else QMessageBox.information
            box(self._ui_parent(), self._window_title, start.message)
            return
        scope_rows = start.scope_rows
        tpsa_col = start.tpsa_col
        logp_col = start.logp_col
        mw_col = start.mw_col
        wlogp_col = start.wlogp_col
        activity_col = start.activity_col
        use_table = start.use_table_columns
        id_col = start.id_col
        src = self.struct_src_combo.currentText()
        self._cancel_snapshot_collect()
        gen = self._snapshot_collect_gen
        export_headers = self._snapshot_export_headers(
            id_col=id_col,
            tpsa_col=tpsa_col,
            logp_col=logp_col,
            mw_col=mw_col,
            wlogp_col=wlogp_col,
            activity_col=activity_col,
            src=src,
            include_structure=not use_table,
        )
        self._snapshot_collect_ctx = {
            "gen": gen,
            "scope_rows": scope_rows,
            "idx": 0,
            "snapshots": [],
            "chunk": self._snapshot_collect_chunk_size(),
            "use_bulk_export": bool(use_table and scope_rows is None and export_headers),
            "export_headers": export_headers,
            "src": src,
            "id_col": id_col,
            "tpsa_col": tpsa_col,
            "logp_col": logp_col,
            "mw_col": mw_col,
            "wlogp_col": wlogp_col,
            "activity_col": activity_col,
        }
        self._set_refresh_ui_busy(True)
        total = self._snapshot_scope_row_count(scope_rows)
        self._set_medchem_status(f"{self._window_title}: reading table… (0/{total:,})")
        QTimer.singleShot(0, self._snapshot_collect_step)

    def _snapshot_collect_step(self) -> None:
        ctx = self._snapshot_collect_ctx
        if not ctx or ctx.get("gen") != self._snapshot_collect_gen:
            return
        app = self.parent_app
        if app is None:
            self._cancel_snapshot_collect()
            self._set_refresh_ui_busy(False)
            return
        scope_rows: list[int] | None = ctx.get("scope_rows")
        idx = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        total = self._snapshot_scope_row_count(scope_rows)
        cfg = load_config()
        deadline = time.monotonic() + max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        model = app._table_model
        snapshots: list[MedChemRowSnapshot] = ctx["snapshots"]
        end = idx
        if ctx.get("use_bulk_export"):
            headers: list[str] = ctx["export_headers"]
            while end < total and (end - idx) < chunk and time.monotonic() < deadline:
                slice_end = min(end + max(64, chunk // 4), total)
                for oid, cells in model.export_rows_for_sqlite_slice(headers, end, slice_end):
                    snapshots.append(
                        self._snapshot_from_cells(
                            oid,
                            cells,
                            id_col=ctx.get("id_col"),
                            tpsa_col=ctx.get("tpsa_col"),
                            logp_col=ctx.get("logp_col"),
                            mw_col=ctx.get("mw_col"),
                            wlogp_col=ctx.get("wlogp_col"),
                            activity_col=ctx.get("activity_col"),
                            src=str(ctx["src"]),
                        )
                    )
                end = slice_end
        else:
            while end < total and (end - idx) < chunk and time.monotonic() < deadline:
                row = int(scope_rows[end] if scope_rows is not None else end)
                snapshots.append(
                    self._snapshot_from_row(
                        row,
                        model=model,
                        src=str(ctx["src"]),
                        id_col=ctx.get("id_col"),
                        tpsa_col=ctx.get("tpsa_col"),
                        logp_col=ctx.get("logp_col"),
                        mw_col=ctx.get("mw_col"),
                        wlogp_col=ctx.get("wlogp_col"),
                        activity_col=ctx.get("activity_col"),
                    )
                )
                end += 1
        ctx["idx"] = end
        self._set_medchem_status(f"{self._window_title}: reading table… ({end:,}/{total:,})")
        if end < total:
            QTimer.singleShot(0, self._snapshot_collect_step)
            return
        self._snapshot_collect_ctx = None
        self._launch_medchem_worker(snapshots)

    def _launch_medchem_worker(self, snapshots: list[MedChemRowSnapshot]) -> None:
        assert self.parent_app is not None
        tpsa_col, logp_col, mw_col, wlogp_col = self._descriptor_column_names()
        use_table = required_descriptor_columns_ok(
            self._plot_kind,
            tpsa_col=tpsa_col,
            logp_col=logp_col,
            mw_col=mw_col,
            wlogp_col=wlogp_col,
        )
        if not use_table and len(snapshots) > 5000:
            self.parent_app.status_label.setText(
                f"{self._window_title}: computing descriptors in the background for "
                f"{len(snapshots):,} compound(s)…"
            )
        if use_table:
            oid_smiles: dict[int, str] = {}
        else:
            oid_smiles = self._oid_smiles_from_cache(snapshots)
        self._bg_cancel_event = threading.Event()
        self._bg_job_id = f"medchem-{id(self)}"
        register_background_job(
            self.parent_app,
            self._bg_job_id,
            self._window_title,
            cancel=self._bg_cancel_event.set,
        )
        self.parent_app._begin_tool_progress(
            self._window_title, len(snapshots), job_id=self._bg_job_id
        )
        progress_state = self.parent_app._tool_progress_state
        bind = getattr(progress_state, "bind", None)
        if callable(bind):
            progress_state = bind(self._bg_job_id)
        params = {
            "snapshots": snapshots,
            "plot_kind": self._plot_kind,
            "tpsa_col": tpsa_col,
            "logp_col": logp_col,
            "mw_col": mw_col,
            "wlogp_col": wlogp_col,
            "use_table_columns_only": use_table,
            "max_plot_points": medchem_plot_max_points(),
            "oid_smiles": oid_smiles,
            "progress_state": progress_state,
            "progress_label": self._window_title,
        }
        worker = MedChemSpaceWorker(
            params,
            self._medchem_signals,
            cancel_event=self._bg_cancel_event,
        )
        self.parent_app.threadpool.start(worker)

    def _clear_medchem_background_job(self) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        if job_id and self.parent_app is not None:
            from ..background_jobs import unregister_background_job

            unregister_background_job(self.parent_app, job_id)
        self._bg_job_id = None

    def _start_refresh_job(self) -> None:
        self._on_refresh()

    def _on_refresh(self) -> None:
        if self.parent_app is None or self._job_running:
            return
        self._cancel_snapshot_collect()
        self._begin_snapshot_collect()

    def _on_build_finished(self, result: object) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        self._clear_medchem_background_job()
        self._set_refresh_ui_busy(False)
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress(self._window_title, job_id=job_id)
        if not isinstance(result, MedChemSpaceBuildResult):
            return
        self._full_dataset = result.full
        self._plot_dataset = result.plot
        total = len(self._full_dataset.points)
        self._log_medchem_summary(
            self._full_dataset.summary_text(plot_kind=self._plot_kind, total_in_scope=total)
        )
        if result.table_updates:
            self._start_table_write_job(list(result.table_updates), list(result.table_columns))
        if not self._plot_dataset.points:
            skipped = self._full_dataset.skipped if self._full_dataset else 0
            detail = (
                f"Could not compute descriptors for any compound in this scope "
                f"({skipped:,} row(s) skipped)."
            )
            if skipped:
                detail += (
                    "\n\nEnsure TPSA, LogP, and MolWt columns are populated, or choose a "
                    "structure source with valid SMILES/mol blocks (Structure column)."
                )
            self._reopen_setup_if_plot_hidden()
            QMessageBox.information(self._ui_parent(), self._window_title, detail)
            return
        if self._plot_kind == "lipe":
            self.reveal_plot_window()
        if self._plot_view is None:
            return
        QTimer.singleShot(0, self._push_plot_figure)
        if self.parent_app is not None:
            shown = len(self._plot_dataset.points)
            n_written = len(result.table_updates)
            extra = f"; wrote descriptors for {n_written:,} row(s)" if n_written else ""
            self.parent_app.status_label.setText(
                f"{self._window_title}: showing {shown:,} of {total:,} compound(s){extra}."
            )

    def _on_build_failed(self, message: str) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        self._clear_medchem_background_job()
        self._set_refresh_ui_busy(False)
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress(job_id=job_id)
        self._reopen_setup_if_plot_hidden()
        QMessageBox.warning(self._ui_parent(), self._window_title, message or "Plot build failed.")

    def _cancel_table_write_job(self) -> None:
        if self._table_writer is not None:
            self._table_writer.cancel()
            self._table_writer = None

    def _start_table_write_job(
        self,
        updates: list[tuple[int, dict[str, str]]],
        columns: list[str],
    ) -> None:
        app = self.parent_app
        if app is None or not updates or not columns:
            return
        app._ensure_columns(columns)
        self._cancel_table_write_job()
        label = f"{self._window_title}: writing descriptors"
        write_job_id = str(uuid.uuid4())[:8]

        def write_chunk(start: int, end: int, _is_last: bool) -> None:
            app._table_model.apply_columns_values_bulk(columns, updates[start:end])

        def on_done() -> None:
            self._table_writer = None
            app._sync_global_bounds_for_headers(columns, refresh_filters=True)
            app._finish_tool_progress(
                f"{self._window_title}: descriptors written",
                job_id=write_job_id,
            )

        app._begin_tool_progress(label, len(updates), job_id=write_job_id)
        self._table_writer = ChunkedTableWriter(
            table=app.table,
            total=len(updates),
            chunk=max(500, load_config().tool_table_chunk_rows // 4),
            write_chunk=write_chunk,
            on_progress=lambda done, total: app._tool_progress_state.update(
                label, done, total, job_id=write_job_id
            ),
            on_done=on_done,
            should_continue=lambda: self.parent_app is not None,
        )
        self._table_writer.start()

    @staticmethod
    def _parse_numeric_cell(text: str) -> float | None:
        s = (text or "").strip().replace(",", "")
        if not s:
            return None
        try:
            v = float(s)
        except ValueError:
            return None
        return v if v == v else None

    def _color_values_for_oids(self, oids: list[int], color_col: str | None) -> list[Any] | None:
        """One color value per plotted OID, in ``dataset.oids`` order (raw table cell)."""
        return self._column_values_for_oids(oids, color_col)

    def _displayed_plot_dataset(self) -> MedChemSpaceDataset | None:
        if self._plot_dataset is None:
            return None
        return self._plot_dataset.subset_oids(
            retained_snapshot_oids(self.parent_app, self._plot_dataset.oids)
        )

    def _push_plot_figure(self) -> None:
        dataset = self._displayed_plot_dataset()
        if self._plot_view is None or dataset is None:
            return
        if not dataset.points:
            from plotly import graph_objects as go

            self._plot_view.push_figure(go.Figure(), [])
            return
        color_col = self.color_combo.currentText()
        if color_col == "(none)":
            color_col = None
        color_vals = self._color_values_for_oids(dataset.oids, color_col)
        from ...plotting.plot_marker_color import normalize_color_column

        color_vals, color_col = normalize_color_column(color_vals, color_col)
        colorscale = self._current_colorscale()
        color_min, color_max = self._current_color_bounds()
        size_col = self.size_combo.currentText()
        if size_col == "(none)":
            size_col = None
        size_vals = self._color_values_for_oids(dataset.oids, size_col)
        size_vals, size_label = normalize_size_column(size_vals, size_col)
        size_min_px, size_max_px = self._current_size_bounds()
        try:
            if self._plot_kind == "golden_triangle":
                fig = build_golden_triangle_figure(
                    dataset,
                    color_values=color_vals,
                    color_label=color_col,
                    colorscale=colorscale,
                    color_min=color_min,
                    color_max=color_max,
                    size_values=size_vals,
                    size_label=size_label,
                    size_min_px=size_min_px,
                    size_max_px=size_max_px,
                    marker_opacity=self._markers_group.marker_opacity(),
                    marker_symbol=self._markers_group.marker_symbol(),
                    **self._titles.title_overrides(),
                )
            elif self._plot_kind == "lipe":
                fig = build_lipe_figure(
                    dataset,
                    color_values=color_vals,
                    color_label=color_col,
                    colorscale=colorscale,
                    color_min=color_min,
                    color_max=color_max,
                    size_values=size_vals,
                    size_label=size_label,
                    size_min_px=size_min_px,
                    size_max_px=size_max_px,
                    marker_opacity=self._markers_group.marker_opacity(),
                    marker_symbol=self._markers_group.marker_symbol(),
                    **self._titles.title_overrides(),
                )
            else:
                fig = build_boiled_egg_figure(
                    dataset,
                    color_values=color_vals,
                    color_label=color_col,
                    colorscale=colorscale,
                    color_min=color_min,
                    color_max=color_max,
                    size_values=size_vals,
                    size_label=size_label,
                    size_min_px=size_min_px,
                    size_max_px=size_max_px,
                    marker_opacity=self._markers_group.marker_opacity(),
                    marker_symbol=self._markers_group.marker_symbol(),
                    **self._titles.title_overrides(),
                )
            self._plot_view.push_figure(fig, dataset.oids)
            self._update_spectrum_controls()
        except Exception as exc:
            QMessageBox.warning(self, self._window_title, f"Plot failed: {exc}")

    def _on_select_in_egg(self) -> None:
        self._select_region_oids(oids_in_egg_gia, region_label="egg")

    def _on_select_in_yolk(self) -> None:
        self._select_region_oids(oids_in_egg_yolk, region_label="yolk")

    def _on_select_in_triangle(self) -> None:
        self._select_region_oids(oids_in_golden_triangle_region, region_label="triangle")

    def _on_select_lipe(self) -> None:
        self._select_region_oids(oids_with_lipe_at_least, region_label="LipE ≥ 5")

    def _select_region_oids(
        self, picker: Callable[[MedChemSpaceDataset], list[int]], *, region_label: str
    ) -> None:
        if self.parent_app is None:
            return
        if self._full_dataset is None or not self._full_dataset.points:
            QMessageBox.information(self, self._window_title, "Refresh the plot first.")
            return
        oids = picker(self._full_dataset)
        keep = retained_snapshot_oids(self.parent_app, oids)
        if keep is not None:
            oids = [int(o) for o in oids if int(o) in keep]
        if not oids:
            QMessageBox.information(
                self,
                self._window_title,
                f"No compounds in the current scope fall within the {region_label} region.",
            )
            return
        extra = f"{self._window_title}: {region_label} region"
        n = self.parent_app.select_table_oids(oids, extra_status=extra)
        if self._plot_view is not None:
            self._plot_view.sync_from_table_selection()
        if n <= 0:
            QMessageBox.information(
                self,
                self._window_title,
                f"No table rows matched the {region_label} region selection.",
            )


def medchem_plot_panel_from_session(
    parent_app: ChemistryWorkspaceWindow | None,
    state: dict | None,
) -> MedChemPlotPanel:
    plot_kind: MedChemPlotKind = "boiled_egg"
    window_title = "BOILED-Egg"
    if isinstance(state, dict):
        pk = state.get("plot_kind")
        if pk in ("boiled_egg", "golden_triangle", "lipe"):
            plot_kind = pk
        wt = state.get("window_title")
        if isinstance(wt, str) and wt.strip():
            window_title = wt.strip()
    panel = MedChemPlotPanel(
        parent_app,
        plot_kind=plot_kind,
        window_title=window_title,
        session_restore=True,
    )
    panel.apply_session_state(state)
    return panel


class MedChemSpaceDialog(QDialog):
    """Floating window for a :class:`MedChemPlotPanel`."""

    def __init__(
        self,
        parent: ChemistryWorkspaceWindow | None,
        *,
        plot_kind: MedChemPlotKind,
        window_title: str,
        panel: MedChemPlotPanel | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self._plot_kind = plot_kind
        if panel is not None:
            self._panel = panel
            self._panel.setParent(self)
            self._panel.parent_app = parent
        else:
            self._panel = MedChemPlotPanel(parent, plot_kind=plot_kind, window_title=window_title)
        self.only_selected_cb = self._panel.only_selected_cb
        self._only_selected_scope_prefix = self._panel._only_selected_scope_prefix

        self.setWindowTitle(window_title)
        self.resize(900, 880)

        root = QVBoxLayout(self)
        root.addWidget(self._panel, 1)
        self._panel._sync_footer_chrome()

        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._force_close = False
        make_window_resizable(self)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        handle_floating_plot_close_event(self, event)
