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

"""Dimred setup opens before the empty plot window; plot settings are appearance only."""

from types import SimpleNamespace

from PyQt5.QtCore import QObject, Qt
from PyQt5.QtWidgets import QGroupBox, QLabel, QListWidgetItem

from molmanager.analysis.dimensionality_reduction import EMBEDDING_PCA_DIM
from molmanager.platform_support.session_log import session_log_buffer
from molmanager.platform_support.tool_progress import ToolProgressState
from molmanager.ui.dialogs.dimensionality_reduction import (
    PCADialog,
    SOMPlotPanel,
    TSNEPlotPanel,
    UMAPPlotPanel,
)
from molmanager.ui.plot_markers_controls import PlotMarkersControls
from molmanager.ui.progress_controller import ProgressController


def test_present_initial_ui_opens_options_not_plot(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel.present_initial_ui()
        qapp.processEvents()
        assert not dlg.isVisible()
        assert panel._opts_dialog.isVisible()
        assert panel._opts_dialog.windowTitle() == "Principal Component Analysis"
        assert not panel._appearance_dialog.isVisible()
        assert not panel._opts_dialog.isAncestorOf(panel._titles)
        assert not panel._opts_dialog.isAncestorOf(panel.color_combo)
    finally:
        panel._opts_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_present_initial_ui_shows_plot_when_result_exists(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel._last_result = object()
        panel.present_initial_ui()
        qapp.processEvents()
        assert dlg.isVisible()
        assert not panel._opts_dialog.isVisible()
    finally:
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_reveal_plot_window_hides_options(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel.present_initial_ui()
        qapp.processEvents()
        panel._last_result = object()
        panel.reveal_plot_window()
        qapp.processEvents()
        assert dlg.isVisible()
        assert not panel._opts_dialog.isVisible()
    finally:
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def _close_dimred_panel(panel, qapp) -> None:
    for name in ("_opts_dialog", "_appearance_dialog"):
        opts = getattr(panel, name, None)
        if opts is not None:
            opts.hide()
            opts.close()
            opts.deleteLater()
    panel.close()
    panel.deleteLater()
    qapp.processEvents()


def test_umap_max_points_spinbox_caps_at_25k(qapp):
    panel = UMAPPlotPanel(None)
    try:
        assert panel.umap_max_points.maximum() == 25_000
        assert panel.umap_max_points.value() == 25_000
    finally:
        _close_dimred_panel(panel, qapp)


def test_embedding_pca_compress_option_defaults_on(qapp):
    for panel_cls in (TSNEPlotPanel, UMAPPlotPanel, SOMPlotPanel):
        panel = panel_cls(None)
        try:
            cb = panel._pca_preprocess_cb
            assert cb is not None
            assert cb.isChecked()
            assert panel._job_method_params()["pca_dim"] == EMBEDDING_PCA_DIM
            assert panel._pca_dim_spin is not None
            assert panel._pca_dim_spin.value() == EMBEDDING_PCA_DIM
            assert panel._pca_var_spin is not None
            assert panel._pca_var_spin.value() == 0
            assert panel._pca_whiten_cb is not None
            assert not panel._pca_whiten_cb.isChecked()
            panel._pca_dim_spin.setValue(25)
            panel._pca_var_spin.setValue(90)
            panel._pca_whiten_cb.setChecked(True)
            params = panel._job_method_params()
            assert params["pca_dim"] == 25
            assert params["pca_min_variance"] == 0.9
            assert params["pca_whiten"] is True
            assert panel._pca_detail_host is not None
            assert panel._pca_detail_host.isVisibleTo(panel._opts_dialog)
            cb.setChecked(False)
            assert not panel._pca_dim_spin.isEnabled()
            assert not panel._pca_detail_host.isVisibleTo(panel._opts_dialog)
            assert panel._job_method_params()["pca_dim"] == 0
            panel._apply_pca_preprocess_param(
                {"pca_dim": 40, "pca_components": 40, "pca_min_variance": 0.8, "pca_whiten": False}
            )
            assert cb.isChecked()
            assert panel._pca_detail_host.isVisibleTo(panel._opts_dialog)
            assert panel._pca_dim_spin.value() == 40
            assert panel._pca_var_spin.value() == 80
            assert not panel._pca_whiten_cb.isChecked()
        finally:
            _close_dimred_panel(panel, qapp)


def test_target_dimensions_switches_pca_between_2d_and_3d(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel.present_initial_ui()
        qapp.processEvents()
        panel._open_plot_options()
        qapp.processEvents()
        assert panel._appearance_dialog.isVisible()
        assert panel.target_dimensions.currentText() == "2D"
        assert panel._job_method_params()["target_dimensions"] == 2
        assert not panel._titles.zaxis_title_edit.isVisible()
        assert panel.pca_components.minimum() == 2

        panel.target_dimensions.setCurrentText("3D")
        qapp.processEvents()
        assert panel._job_method_params()["target_dimensions"] == 3
        assert panel.pca_components.minimum() == 3
        assert panel.pca_components.value() >= 3
        assert panel._titles.zaxis_title_edit.isVisible()

        panel.pca_components.setValue(8)
        panel.apply_session_state({"method_params": {"target_dimensions": 2, "n_components": 4}})
        qapp.processEvents()
        assert panel.target_dimensions.currentText() == "2D"
        assert panel.pca_components.value() == 4
        assert panel.pca_components.minimum() == 2
        assert not panel._titles.zaxis_title_edit.isVisible()
    finally:
        panel._opts_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_som_map_depth_is_used_for_3d_only(qapp):
    panel = SOMPlotPanel(None)
    try:
        assert not panel.som_grid_d.isEnabled()
        assert panel.som_grid_d.value() == 5
        params = panel._job_method_params()
        assert params["target_dimensions"] == 2
        assert params["grid_depth"] == 5

        panel.target_dimensions.setCurrentText("3D")
        qapp.processEvents()
        assert panel.som_grid_d.isEnabled()
        panel.som_grid_d.setValue(4)
        params = panel._job_method_params()
        assert params["target_dimensions"] == 3
        assert params["grid_depth"] == 4
    finally:
        _close_dimred_panel(panel, qapp)


class _StatusLabel:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:  # noqa: N802 — Qt-shaped stand-in
        self.text = text


class _RunHost:
    def __init__(self) -> None:
        self.status_label = _StatusLabel()
        self.began: list[tuple] = []

    def _begin_tool_progress(self, message: str, total: int, job_id: str | None = None) -> None:
        self.began.append((message, total, job_id))
        self.status_label.setText(message)

    def raise_(self) -> None:
        return None

    def activateWindow(self) -> None:  # noqa: N802 — Qt-shaped stand-in
        return None


def test_dimred_options_omit_results_section(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        labels = [w.text() for w in panel._opts_dialog.findChildren(QLabel)]
        assert "Results" not in labels
        assert not hasattr(panel, "summary_text")
    finally:
        panel._opts_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


class _DimredStatusHost(QObject):
    """Main-window stand-in with the real progress controller."""

    def __init__(self) -> None:
        super().__init__()
        self.status_label = QLabel("Ready")
        self._tool_progress_state = ToolProgressState()
        self.background_activity = None
        self._loading_detail = None
        self._export_busy = False
        self.process_queue = None
        self._background_jobs: dict[str, str] = {}
        self.progress = ProgressController(self)

    def _begin_tool_progress(self, *args, **kwargs):
        return self.progress._begin_tool_progress(*args, **kwargs)

    def _finish_tool_progress(self, *args, **kwargs):
        return self.progress._finish_tool_progress(*args, **kwargs)

    def _end_slots_with_message(self, message: str) -> None:
        self.progress._end_slots_with_message(message)

    def _workspace_loading_overlay_visible(self) -> bool:
        return False

    def _session_overlay_owns_loading_detail(self) -> bool:
        return False

    def _status_work_is_active(self) -> bool:
        return bool(self._background_jobs) or self._tool_progress_state.any_active()


def test_finished_embedding_clears_calculating_status_even_if_draw_fails(qapp):
    for panel_cls, job_id in ((TSNEPlotPanel, "dimred-tsne"), (UMAPPlotPanel, "dimred-umap")):
        panel = panel_cls(None)
        host = _DimredStatusHost()
        panel.parent_app = host
        panel._bg_job_id = job_id
        host._background_jobs[job_id] = f"{panel._window_title}…"
        host._begin_tool_progress(panel._calculating_status_text(), -1, job_id=job_id)
        assert host.status_label.text() == panel._calculating_status_text()

        def _boom(status_host=host) -> None:
            assert "calculating" not in status_host.status_label.text()
            raise RuntimeError("draw failed")

        panel._plot_view = object()
        panel._refresh_plot_colors = _boom  # type: ignore[method-assign]
        result = SimpleNamespace(summary="Samples used: 4", z=None)
        try:
            try:
                panel._on_finished(result)
            except RuntimeError as exc:
                assert str(exc) == "draw failed"
            assert "calculating" not in host.status_label.text()
            assert host.status_label.text() == f"{panel._window_title}: done."
            assert host._tool_progress_state.any_active() is False
            host.progress._on_tool_progress(panel._calculating_status_text(), 0, -1, job_id=job_id)
            host.progress._poll_tool_progress_state()
            qapp.processEvents()
            assert "calculating" not in host.status_label.text()
        finally:
            _close_dimred_panel(panel, qapp)


def test_run_closes_options_and_sets_calculating_status(qapp):
    dlg = PCADialog(None)
    panel = dlg._panel
    host = _RunHost()
    panel.parent_app = host
    item = QListWidgetItem("MW")
    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
    item.setCheckState(Qt.Checked)
    panel.column_list.addItem(item)
    try:
        panel.present_initial_ui()
        qapp.processEvents()
        assert panel._opts_dialog.isVisible()
        panel._on_run()
        assert not panel._opts_dialog.isVisible()
        assert panel._job_running
        assert host.status_label.text == "Principal Component Analysis: calculating…"
        assert "%" not in host.status_label.text
        assert host.began == []
        panel._bg_job_id = "dimred-test"
        panel._show_calculating_status()
        assert host.began == [("Principal Component Analysis: calculating…", -1, "dimred-test")]
        assert "%" not in host.status_label.text
    finally:
        panel._job_running = False
        panel._opts_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_dimred_summary_is_written_to_the_session_log(qapp):
    session_log_buffer().clear()
    dlg = PCADialog(None)
    try:
        dlg._panel._log_dimred_summary("Samples used: 4\nFeatures: 2")
        entries, _seq, _gen = session_log_buffer().snapshot()
        assert any(
            "Principal Component Analysis" in entry.message and "Samples used: 4" in entry.message
            for entry in entries
        )
    finally:
        session_log_buffer().clear()
        dlg._panel._opts_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_plot_options_split_embedding_and_appearance(qapp):
    panel = UMAPPlotPanel(None)
    try:
        titles = [box.title() for box in panel._opts_dialog.findChildren(QGroupBox)]
        assert "Features" in titles
        assert "Scope" in titles
        assert "Method" in titles
        assert "Preprocess" in titles
        assert "Points" in titles
        assert "Appearance" not in titles
        labels = [w.text() for w in panel._opts_dialog.findChildren(QLabel)]
        assert "Neighbors:" in labels
        assert "Min distance:" in labels
        assert "n_neighbors:" not in labels
        assert "min_dist:" not in labels
        assert "Color by:" not in labels
        assert not panel._opts_dialog.isAncestorOf(panel.color_combo)
        assert not panel._opts_dialog.isAncestorOf(panel._titles)
        panel._open_plot_options()
        qapp.processEvents()
        assert panel._appearance_dialog.isVisible()
        assert not panel._opts_dialog.isVisible()
        assert panel._appearance_dialog.windowTitle() == "UMAP Visualization — Plot Options"
        assert panel._appearance_dialog.isAncestorOf(panel.color_combo)
        assert panel._appearance_dialog.isAncestorOf(panel._titles)
        assert panel._appearance_dialog.isAncestorOf(panel._hover_controls)
        assert panel._appearance_dialog.isAncestorOf(panel.size_combo)
        markers = panel._markers_group
        assert isinstance(markers, PlotMarkersControls)
        assert markers.title() == "Markers"
        assert markers.isAncestorOf(panel.color_combo)
        assert markers.isAncestorOf(panel.size_combo)
        assert not panel._titles.isAncestorOf(panel.color_combo)
        assert not panel._hover_controls.isAncestorOf(panel.size_combo)
        assert not panel._appearance_dialog.isAncestorOf(panel.column_list)
        assert not panel._appearance_dialog.isAncestorOf(panel.run_btn)
    finally:
        _close_dimred_panel(panel, qapp)


def test_som_method_groups(qapp):
    panel = SOMPlotPanel(None)
    try:
        titles = [box.title() for box in panel._opts_dialog.findChildren(QGroupBox)]
        assert "Map" in titles
        assert "Training" in titles
        assert "Points" in titles
        labels = [w.text() for w in panel._opts_dialog.findChildren(QLabel)]
        assert "Width:" in labels
        assert "Height:" in labels
        assert "Depth:" in labels
        assert "Jitter:" in labels
    finally:
        _close_dimred_panel(panel, qapp)


def test_setup_dialog_stays_free_of_appearance_after_a_result(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel.apply_session_state(
            {
                "result": {
                    "method": "pca",
                    "x": [0.0],
                    "y": [1.0],
                    "oids": [1],
                    "hover": ["a"],
                    "title": "PCA",
                    "summary": "",
                }
            }
        )
        qapp.processEvents()
        assert not panel._opts_dialog.isAncestorOf(panel._titles)
        assert not panel._opts_dialog.isAncestorOf(panel.color_combo)
        panel._open_setup_dialog()
        qapp.processEvents()
        assert panel._opts_dialog.isVisible()
        assert not panel._appearance_dialog.isVisible()
    finally:
        panel._opts_dialog.hide()
        panel._appearance_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_pca_plot_has_no_preprocess_checkbox(qapp):
    dlg = PCADialog(None)
    try:
        assert dlg._panel._pca_preprocess_cb is None
        assert "pca_dim" not in dlg._panel._job_method_params()
    finally:
        dlg._panel._opts_dialog.hide()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()
