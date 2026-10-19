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

"""PCA, t-SNE, UMAP, and SOM visualization dialogs (Data menu)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
)

from ..dockable_plot import handle_floating_plot_close_event
from ..qt_widget_utils import make_window_minimizable
from .dimred_panel import DimensionReductionPanel

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow


def _plain_form() -> QFormLayout:
    """Form whose margins come from the group box around it."""
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    return form


def _max_points_spin() -> QSpinBox:
    """Row cap shared by t-SNE, UMAP, and SOM."""
    from ...platform_support.config import load_config

    spin = QSpinBox()
    cap = int(load_config().memory_guard_dimred_max_points)
    spin.setRange(100, cap)
    spin.setValue(min(2500, cap))
    spin.setToolTip("Subsample to this many rows when the table is larger (cap 25,000).")
    return spin


def _seed_spin() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 999_999)
    spin.setValue(42)
    return spin


def _points_group(*rows: tuple[str, QSpinBox | QDoubleSpinBox]) -> QGroupBox:
    """Sampling and draw knobs that are not the embedding algorithm itself."""
    box = QGroupBox("Points")
    form = QFormLayout(box)
    for label, widget in rows:
        form.addRow(label, widget)
    return box


class DimensionReductionDialog(QDialog):
    """Floating window hosting a :class:`DimensionReductionPanel`."""

    def __init__(
        self,
        parent: ChemistryWorkspaceWindow | None,
        *,
        panel: DimensionReductionPanel,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self._panel = panel
        self._panel.setParent(self)
        self._panel.parent_app = parent
        self.only_selected_cb = self._panel.only_selected_cb
        self._only_selected_scope_prefix = self._panel._only_selected_scope_prefix

        self.setWindowTitle(panel._window_title)
        self.resize(900, 900)

        root = QVBoxLayout(self)
        root.addWidget(self._panel, 1)
        self._panel._sync_footer_chrome()

        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._force_close = False
        make_window_minimizable(self)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        handle_floating_plot_close_event(self, event)


class PCAPlotPanel(DimensionReductionPanel):
    """Principal component analysis on numeric table columns."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent, window_title="Principal Component Analysis", method="pca")

    def _build_method_options(self, layout: QVBoxLayout) -> None:
        form = _plain_form()
        self.pca_components = QSpinBox()
        self.pca_components.setRange(2, 50)
        self.pca_components.setValue(2)
        self.pca_components.setToolTip(
            "Number of principal components to compute. The plot shows the first two or three, "
            "depending on Target Dimensions."
        )
        form.addRow("Components:", self.pca_components)
        layout.addLayout(form)

    def _on_target_dimensions_changed(self, is_3d: bool) -> None:
        self.pca_components.setMinimum(3 if is_3d else 2)
        if is_3d and self.pca_components.value() < 3:
            self.pca_components.setValue(3)

    def _method_params(self) -> dict:
        return {"n_components": int(self.pca_components.value())}

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        n = params.get("n_components")
        if isinstance(n, int):
            self.pca_components.setValue(max(2, min(50, n)))


class PCADialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemistryWorkspaceWindow | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or PCAPlotPanel(parent))


class TSNEPlotPanel(DimensionReductionPanel):
    """t-SNE embedding of numeric table columns."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent, window_title="t-SNE Visualization", method="tsne")

    def _build_method_options(self, layout: QVBoxLayout) -> None:
        form = _plain_form()
        self.tsne_perplexity = QDoubleSpinBox()
        self.tsne_perplexity.setRange(5.0, 500.0)
        self.tsne_perplexity.setDecimals(1)
        self.tsne_perplexity.setValue(30.0)
        form.addRow("Perplexity:", self.tsne_perplexity)

        self.tsne_learning_rate = QDoubleSpinBox()
        self.tsne_learning_rate.setRange(10.0, 1000.0)
        self.tsne_learning_rate.setDecimals(0)
        self.tsne_learning_rate.setValue(200.0)
        form.addRow("Learning rate:", self.tsne_learning_rate)

        self.tsne_max_iter = QSpinBox()
        self.tsne_max_iter.setRange(250, 10000)
        self.tsne_max_iter.setSingleStep(250)
        self.tsne_max_iter.setValue(1000)
        form.addRow("Max iterations:", self.tsne_max_iter)
        layout.addLayout(form)

        self.tsne_max_points = _max_points_spin()
        self.tsne_seed = _seed_spin()
        layout.addWidget(
            _points_group(
                ("Max points:", self.tsne_max_points),
                ("Random seed:", self.tsne_seed),
            )
        )

    def _method_params(self) -> dict:
        return {
            "perplexity": float(self.tsne_perplexity.value()),
            "learning_rate": float(self.tsne_learning_rate.value()),
            "max_iter": int(self.tsne_max_iter.value()),
            "max_points": int(self.tsne_max_points.value()),
            "random_state": int(self.tsne_seed.value()),
        }

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        if params.get("perplexity") is not None:
            self.tsne_perplexity.setValue(float(params["perplexity"]))
        if params.get("learning_rate") is not None:
            self.tsne_learning_rate.setValue(float(params["learning_rate"]))
        if isinstance(params.get("max_iter"), int):
            self.tsne_max_iter.setValue(int(params["max_iter"]))
        if isinstance(params.get("max_points"), int):
            self.tsne_max_points.setValue(int(params["max_points"]))
        if isinstance(params.get("random_state"), int):
            self.tsne_seed.setValue(int(params["random_state"]))


class TSNEVisualizationDialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemistryWorkspaceWindow | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or TSNEPlotPanel(parent))


class UMAPPlotPanel(DimensionReductionPanel):
    """UMAP embedding of numeric table columns or fingerprints."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent, window_title="UMAP Visualization", method="umap")

    def _build_method_options(self, layout: QVBoxLayout) -> None:
        form = _plain_form()
        self.umap_neighbors = QSpinBox()
        self.umap_neighbors.setRange(2, 200)
        self.umap_neighbors.setValue(15)
        self.umap_neighbors.setToolTip(
            "Local neighborhood size; lower values emphasize fine structure, higher values global layout."
        )
        form.addRow("Neighbors:", self.umap_neighbors)

        self.umap_min_dist = QDoubleSpinBox()
        self.umap_min_dist.setRange(0.0, 0.99)
        self.umap_min_dist.setDecimals(2)
        self.umap_min_dist.setSingleStep(0.05)
        self.umap_min_dist.setValue(0.1)
        self.umap_min_dist.setToolTip(
            "Minimum spacing between embedded points (0 = tight clusters, ~1 = spread out)."
        )
        form.addRow("Min distance:", self.umap_min_dist)
        layout.addLayout(form)

        self.umap_max_points = _max_points_spin()
        self.umap_seed = _seed_spin()
        layout.addWidget(
            _points_group(
                ("Max points:", self.umap_max_points),
                ("Random seed:", self.umap_seed),
            )
        )

    def _method_params(self) -> dict:
        return {
            "n_neighbors": int(self.umap_neighbors.value()),
            "min_dist": float(self.umap_min_dist.value()),
            "max_points": int(self.umap_max_points.value()),
            "random_state": int(self.umap_seed.value()),
        }

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        if isinstance(params.get("n_neighbors"), int):
            self.umap_neighbors.setValue(int(params["n_neighbors"]))
        if params.get("min_dist") is not None:
            self.umap_min_dist.setValue(float(params["min_dist"]))
        if isinstance(params.get("max_points"), int):
            self.umap_max_points.setValue(int(params["max_points"]))
        if isinstance(params.get("random_state"), int):
            self.umap_seed.setValue(int(params["random_state"]))


class UMAPVisualizationDialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemistryWorkspaceWindow | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or UMAPPlotPanel(parent))


class SOMPlotPanel(DimensionReductionPanel):
    """Kohonen self-organizing map of numeric columns and/or fingerprints."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent, window_title="Self-Organizing Map", method="som")

    def _build_method_options(self, layout: QVBoxLayout) -> None:
        self.som_grid_w = QSpinBox()
        self.som_grid_w.setRange(2, 40)
        self.som_grid_w.setValue(10)
        self.som_grid_w.setToolTip("Number of map columns (X). Nodes = width × height (max 2,500).")

        self.som_grid_h = QSpinBox()
        self.som_grid_h.setRange(2, 40)
        self.som_grid_h.setValue(10)
        self.som_grid_h.setToolTip("Number of map rows (Y). Nodes = width × height (max 2,500).")

        self.som_grid_d = QSpinBox()
        self.som_grid_d.setRange(2, 20)
        self.som_grid_d.setValue(5)
        self.som_grid_d.setToolTip(
            "Number of map layers (Z) when Target Dimensions is 3D. "
            "Nodes = width × height × depth (max 2,500)."
        )

        map_box = QGroupBox("Map")
        map_form = QFormLayout(map_box)
        map_form.addRow("Width:", self.som_grid_w)
        map_form.addRow("Height:", self.som_grid_h)
        map_form.addRow("Depth:", self.som_grid_d)
        layout.addWidget(map_box)

        self.som_epochs = QSpinBox()
        self.som_epochs.setRange(5, 500)
        self.som_epochs.setValue(50)
        self.som_epochs.setToolTip("Training epochs; each epoch presents every sample once.")

        self.som_lr = QDoubleSpinBox()
        self.som_lr.setRange(0.01, 1.0)
        self.som_lr.setDecimals(2)
        self.som_lr.setSingleStep(0.05)
        self.som_lr.setValue(0.5)
        self.som_lr.setToolTip("Initial learning rate (decays linearly to near zero).")

        self.som_sigma = QDoubleSpinBox()
        self.som_sigma.setRange(0.0, 40.0)
        self.som_sigma.setDecimals(1)
        self.som_sigma.setSingleStep(0.5)
        self.som_sigma.setValue(0.0)
        self.som_sigma.setSpecialValueText("auto (½ max side)")
        self.som_sigma.setToolTip(
            "Initial neighborhood radius in node units. 0 = half the longer map side."
        )

        training = QGroupBox("Training")
        training_form = QFormLayout(training)
        training_form.addRow("Epochs:", self.som_epochs)
        training_form.addRow("Learning rate:", self.som_lr)
        training_form.addRow("Sigma:", self.som_sigma)
        layout.addWidget(training)

        self.som_jitter = QDoubleSpinBox()
        self.som_jitter.setRange(0.0, 0.5)
        self.som_jitter.setDecimals(2)
        self.som_jitter.setSingleStep(0.05)
        self.som_jitter.setValue(0.35)
        self.som_jitter.setToolTip(
            "Jitter BMU coordinates so compounds on the same node do not stack exactly."
        )
        self.som_max_points = _max_points_spin()
        self.som_seed = _seed_spin()
        layout.addWidget(
            _points_group(
                ("Jitter:", self.som_jitter),
                ("Max points:", self.som_max_points),
                ("Random seed:", self.som_seed),
            )
        )

    def _on_target_dimensions_changed(self, is_3d: bool) -> None:
        self.som_grid_d.setEnabled(is_3d)

    def _method_params(self) -> dict:
        return {
            "grid_width": int(self.som_grid_w.value()),
            "grid_height": int(self.som_grid_h.value()),
            "grid_depth": int(self.som_grid_d.value()),
            "n_epochs": int(self.som_epochs.value()),
            "learning_rate": float(self.som_lr.value()),
            "sigma": float(self.som_sigma.value()),
            "jitter": float(self.som_jitter.value()),
            "max_points": int(self.som_max_points.value()),
            "random_state": int(self.som_seed.value()),
        }

    def _apply_method_params(self, params: dict | None) -> None:
        if not isinstance(params, dict):
            return
        for key, spin in (
            ("grid_width", self.som_grid_w),
            ("grid_height", self.som_grid_h),
            ("grid_depth", self.som_grid_d),
            ("n_epochs", self.som_epochs),
            ("max_points", self.som_max_points),
            ("random_state", self.som_seed),
        ):
            if isinstance(params.get(key), int):
                spin.setValue(int(params[key]))
        for key, spin in (
            ("learning_rate", self.som_lr),
            ("sigma", self.som_sigma),
            ("jitter", self.som_jitter),
        ):
            if params.get(key) is not None:
                spin.setValue(float(params[key]))


class SOMVisualizationDialog(DimensionReductionDialog):
    def __init__(
        self,
        parent: ChemistryWorkspaceWindow | None = None,
        *,
        panel: DimensionReductionPanel | None = None,
    ):
        super().__init__(parent, panel=panel or SOMPlotPanel(parent))


DIMRED_FLOATING_DIALOGS = {
    "pca": PCADialog,
    "tsne": TSNEVisualizationDialog,
    "umap": UMAPVisualizationDialog,
    "som": SOMVisualizationDialog,
}

_DIMRED_PANELS = {
    "pca": PCAPlotPanel,
    "tsne": TSNEPlotPanel,
    "umap": UMAPPlotPanel,
    "som": SOMPlotPanel,
}


def dimension_reduction_panel_from_session(
    parent_app: ChemistryWorkspaceWindow | None,
    state: dict | None,
) -> DimensionReductionPanel:
    method = "pca"
    if isinstance(state, dict):
        method = str(state.get("method") or "pca")
    panel_cls = _DIMRED_PANELS.get(method, PCAPlotPanel)
    panel = panel_cls(parent_app)
    panel.apply_session_state(state)
    return panel
