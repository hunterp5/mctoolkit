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

"""Dimred Plot Options open before the empty plot window."""

from molmanager.analysis.dimensionality_reduction import EMBEDDING_PCA_DIM
from molmanager.ui.dialogs.dimensionality_reduction import (
    PCADialog,
    SOMPlotPanel,
    TSNEPlotPanel,
    UMAPPlotPanel,
)


def test_present_initial_ui_opens_options_not_plot(qapp):
    dlg = PCADialog(None)
    try:
        panel = dlg._panel
        panel.present_initial_ui()
        qapp.processEvents()
        assert not dlg.isVisible()
        assert panel._opts_dialog.isVisible()
        assert panel._opts_dialog.windowTitle() == "Principal Component Analysis — Plot Options"
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
    opts = getattr(panel, "_opts_dialog", None)
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
        assert panel.umap_max_points.value() == 2500
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
            cb.setChecked(False)
            assert not panel._pca_dim_spin.isEnabled()
            assert panel._job_method_params()["pca_dim"] == 0
            panel._apply_pca_preprocess_param(
                {"pca_dim": 40, "pca_components": 40, "pca_min_variance": 0.8, "pca_whiten": False}
            )
            assert cb.isChecked()
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
