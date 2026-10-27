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

"""Qt widgets that host the ligand 3Dmol.js viewer."""

from __future__ import annotations

import base64
import json
import logging
import shutil
from contextlib import suppress
from pathlib import Path

from PyQt5.QtCore import QTemporaryDir, QTimer, QUrl, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from ..platform_support.qt_webengine_flags import (
    apply_viewer_webengine_settings,
    refuse_remote_viewer_script,
    webengine_views_supported,
)
from .dockable_plot import (
    PLOT_BODY_MARGINS,
    PLOT_BODY_SPACING,
    make_add_to_main_button,
    make_plot_options_button,
    make_plot_options_dialog,
    make_send_window_button,
    style_plot_footer_text_button,
)
from .mol_3d_chrome_mixin import Mol3DChromeMixin
from .mol_3d_conf_mixin import Mol3DConfMixin
from .mol_3d_embed import Molecule3DEmbedView
from .mol_3d_html import (
    _BUNDLED_3DMOL,
    _cdn_fallback_html,
    _cdn_fallback_html_multiconf,
    _mol_block_b64,
    _offline_index_html,
    _offline_index_html_multiconf,
    _wire_webengine_console_logger,
    bundled_3dmol_available,
)
from .mol_3d_strain import populate_strain_energy_table
from .property_columns_panel import (
    PROPERTY_COLUMN_SLOT_COUNT,
    PROPERTY_COLUMN_SLOT_MAX,
    PropertyColumnsPanel,
)
from .qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)

__all__ = [
    "Molecule3DEmbedView",
    "Molecule3DViewerWidget",
    "populate_strain_energy_table",
]


def _multi_conf_block_count(blocks_json_b64: str | None) -> int:
    """Number of packed conformer mol-blocks in a viewer payload."""
    raw = (blocks_json_b64 or "").strip()
    if not raw:
        return 0
    try:
        blocks = json.loads(base64.b64decode(raw.encode("ascii")))
    except Exception:
        return 0
    return len(blocks) if isinstance(blocks, list) else 0


class Molecule3DViewerWidget(Mol3DConfMixin, Mol3DChromeMixin, QWidget):
    """Interactive 3Dmol structure viewer; float or dock beside the compound table.

    ``Mol3DConfMixin`` / ``Mol3DChromeMixin`` are a file-split of this widget.
    """

    dockable_in_workspace = True

    def __init__(
        self,
        mol: Chem.Mol,
        parent_app: QWidget | None = None,
        *,
        window_title: str = "View in 3D",
        flat: bool = False,
        multi_conf_blocks_json_b64: str | None = None,
        multi_conf_initial_superpose: bool = False,
        multi_conf_strain_overlay_json_b64: str = "",
        multi_conf_initial_index: int = 0,
        export_parent_oid: int | None = None,
        export_confs_column: str = "confs",
        strain_overlay: dict | None = None,
        source_oid: int | None = None,
    ):
        super().__init__(None)
        self.parent_app = parent_app
        self._window_title = window_title
        self._flat = bool(flat)
        if source_oid is None:
            source_oid = export_parent_oid
        try:
            self._source_oid = int(source_oid) if source_oid is not None else None
        except (TypeError, ValueError):
            self._source_oid = None

        self._multi_conf_blocks_b64 = multi_conf_blocks_json_b64
        self._export_parent_oid = export_parent_oid
        self._export_confs_column = (export_confs_column or "confs").strip() or "confs"
        self._strain_overlay = dict(strain_overlay) if strain_overlay else None
        if self._strain_overlay is None and multi_conf_strain_overlay_json_b64:
            try:
                self._strain_overlay = json.loads(
                    base64.b64decode(multi_conf_strain_overlay_json_b64.encode("ascii"))
                )
            except Exception:
                self._strain_overlay = None
        try:
            self._initial_conf_index = max(0, int(multi_conf_initial_index))
        except (TypeError, ValueError):
            self._initial_conf_index = 0
        self._conf_mode_busy = False
        self._web_refit_size: tuple[int, int] | None = None
        self._web_did_initial_zoom = False

        mol_b64 = _mol_block_b64(mol) if multi_conf_blocks_json_b64 is None else ""
        self._viewer_tmp: QTemporaryDir | None = None
        self._prop_panel: PropertyColumnsPanel | None = None
        self._prop_refresh_wired = False
        self._prop_refresh_timer: QTimer | None = None
        self._prop_refresh_schedule = None
        self._prop_refresh_signals: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(*PLOT_BODY_MARGINS)
        root.setSpacing(PLOT_BODY_SPACING)

        web = None
        try:
            if not webengine_views_supported():
                raise RuntimeError("WebEngine is unavailable on this platform plugin")
            from PyQt5.QtWebEngineWidgets import QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            _wire_webengine_console_logger(web)
            with suppress(Exception):
                apply_viewer_webengine_settings(web.settings())
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                if multi_conf_blocks_json_b64 is not None:
                    index.write_text(
                        _offline_index_html_multiconf(
                            multi_conf_blocks_json_b64,
                            initial_superpose=multi_conf_initial_superpose,
                            initial_conf_index=multi_conf_initial_index,
                        ),
                        encoding="utf-8",
                    )
                else:
                    index.write_text(_offline_index_html(mol_b64, flat=flat), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                refuse_remote_viewer_script()
                if multi_conf_blocks_json_b64 is not None:
                    web.setHtml(
                        _cdn_fallback_html_multiconf(
                            multi_conf_blocks_json_b64,
                            initial_superpose=multi_conf_initial_superpose,
                            initial_conf_index=multi_conf_initial_index,
                        ),
                        QUrl("https://3dmol.org/"),
                    )
                else:
                    web.setHtml(_cdn_fallback_html(mol_b64, flat=flat), QUrl("https://3dmol.org/"))
            web.loadFinished.connect(lambda _ok: self._on_standalone_viewer_ready(web))
            web.setMinimumHeight(160)
            web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            root.addWidget(web, 1)
            self._standalone_web = web
        except Exception as e:
            web = None
            self._standalone_web = None
            err = f"{type(e).__name__}: {e}"
            logger.warning("Embedded 3Dmol viewer unavailable: %s", err, exc_info=True)
            msg = (
                "The embedded viewer could not start.\n\n"
                f"{err}\n\n"
                "Typical fixes:\n"
                "• Install PyQtWebEngine with the same major.minor version as PyQt5 (e.g. both 5.15.x).\n"
                "• Start molmanager with `python -m molmanager` so QtWebEngine loads before the GUI initializes.\n\n"
                "Close this window when you are done."
            )
            root.addWidget(QLabel(msg), 1)

        self._strain_table: QTableWidget | None = None
        self._cb_only_selected_confs: QCheckBox | None = None
        if self._strain_overlay:
            self._strain_table = self._build_strain_energy_table()
            root.addWidget(self._strain_table, 0)

        self._conf_nav_host: QWidget | None = None
        self._conf_count = _multi_conf_block_count(multi_conf_blocks_json_b64)
        self._conf_idx = int(getattr(self, "_initial_conf_index", 0) or 0)
        if self._conf_count > 0:
            self._conf_idx = max(0, min(self._conf_idx, self._conf_count - 1))
        self._conf_superposed = bool(multi_conf_initial_superpose) and self._conf_count >= 2

        self._export_host = None
        self._btn_export_table = None
        self._viewer_status = None
        self._opts_btn = None
        self._opts_dialog = None
        self._cb_hide_options = None
        self._spin_field_count = None
        self._options_visible = True

        self._options_host = QWidget(self)
        options_ly = QVBoxLayout(self._options_host)
        options_ly.setContentsMargins(0, 0, 0, 0)
        options_ly.setSpacing(4)
        self._options_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        # View Conformers is multi-conf; skip table field pickers (Browser shows the row table).
        if multi_conf_blocks_json_b64 is None:
            self._prop_panel = PropertyColumnsPanel(self._options_host)
            self._prop_panel.bind_app(parent_app)
            self._prop_panel.set_source_oid(self._source_oid)
            options_ly.addWidget(self._prop_panel)
            self._wire_property_column_updates()
            root.addWidget(self._options_host)
        else:
            self._prop_panel = None
            self._options_host.hide()

        footer = QWidget(self)
        footer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._footer_bar = footer
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        if self._prop_panel is not None:
            self._opts_btn = make_plot_options_button(
                self,
                tooltip="Viewer settings: data fields and options visibility.",
            )
            self._opts_btn.clicked.connect(self._open_viewer_options)
            foot.addWidget(self._opts_btn)
            self._opts_panel = QWidget(self)
            opts_form = QFormLayout(self._opts_panel)
            opts_form.setContentsMargins(0, 0, 0, 0)
            opts_form.setHorizontalSpacing(10)
            opts_form.setVerticalSpacing(8)
            self._cb_hide_options = QCheckBox("Hide Options")
            self._cb_hide_options.setToolTip(
                "Hide column pickers so only the structure view and navigation controls are shown."
            )
            self._cb_hide_options.toggled.connect(self._on_hide_options_toggled)
            opts_form.addRow(self._cb_hide_options)
            self._spin_field_count = QSpinBox()
            self._spin_field_count.setRange(0, PROPERTY_COLUMN_SLOT_MAX)
            self._spin_field_count.setValue(PROPERTY_COLUMN_SLOT_COUNT)
            self._spin_field_count.setToolTip(
                "How many table data fields to show under the structure view."
            )
            self._spin_field_count.valueChanged.connect(self._on_field_count_changed)
            opts_form.addRow("Data fields:", self._spin_field_count)
            self._opts_dialog = make_plot_options_dialog(
                self,
                self._opts_panel,
                title="Viewer Settings",
                min_width=320,
                min_height=140,
            )
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this viewer beside the table in the main window (like a plot pane).",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked viewer in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        self._close_viewer_btn = QPushButton("Close")
        self._close_viewer_btn.setToolTip("Close this viewer.")
        self._close_viewer_btn.clicked.connect(self._close_docked_viewer)
        style_plot_footer_text_button(self._close_viewer_btn)
        foot.addStretch(1)
        foot.addWidget(self._add_to_main_btn)
        foot.addWidget(self._send_window_btn)
        foot.addWidget(self._close_viewer_btn)
        self._apply_footer_size_constraints(foot)
        root.insertWidget(0, footer)

        if multi_conf_blocks_json_b64 is not None:
            nav = QWidget(self)
            nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            nav_row = QHBoxLayout(nav)
            nav_row.setContentsMargins(0, 0, 0, 0)
            nav_row.setSpacing(4)
            self._add_conf_nav_controls(nav_row)
            self._btn_export_table = QPushButton("Export to Table")
            self._btn_export_table.setAutoDefault(False)
            self._btn_export_table.setDefault(False)
            self._btn_export_table.setToolTip(
                "Add the current conformer (or all when superposed) to the main table. "
                "Writes 2D Structure, optional E / ΔE / RMSD, and packed 3D into confs when present."
            )
            self._btn_export_table.clicked.connect(self._on_export_to_table)
            if web is None:
                self._btn_export_table.setEnabled(False)
            nav_row.addWidget(self._btn_export_table)
            nav_row.addStretch(1)
            self._viewer_status = QLabel("")
            self._viewer_status.setStyleSheet("color: #333;")
            self._viewer_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            nav_row.addWidget(self._viewer_status)
            self._apply_footer_size_constraints(nav_row)
            root.addWidget(nav)
            self._conf_nav_host = nav
            self._export_host = nav

        self._sync_footer_chrome()
        self._sync_options_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

    def _wire_property_column_updates(self) -> None:
        """Refresh property values when table cells/headers change."""
        if self._prop_refresh_wired:
            return
        app = self.parent_app
        model = getattr(app, "_table_model", None) if app is not None else None
        if model is None:
            return
        self._prop_refresh_wired = True
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(80)
        self._prop_refresh_timer = timer

        def _refresh() -> None:
            if qobject_is_deleted(self):
                return
            panel = self._prop_panel
            if panel is None:
                return
            panel.refresh_columns()
            panel.update_values()

        timer.timeout.connect(_refresh)

        def _schedule(*_args) -> None:
            if qobject_is_deleted(self):
                return
            t = self._prop_refresh_timer
            if t is None or qobject_is_deleted(t):
                return
            try:
                t.start()
            except RuntimeError:
                return

        self._prop_refresh_schedule = _schedule
        signals = [
            model.dataChanged,
            model.rowsInserted,
            model.rowsRemoved,
            model.modelReset,
            model.layoutChanged,
            model.columnsInserted,
            model.columnsRemoved,
        ]
        try:
            signals.append(model.headerDataChanged)
        except Exception:
            pass
        self._prop_refresh_signals = signals
        for sig in signals:
            sig.connect(_schedule)
        self.destroyed.connect(self._unwire_property_column_updates)

    def _unwire_property_column_updates(self, *_args) -> None:
        """Drop table-model connections so a deleted viewer cannot restart its QTimer."""
        slot = self._prop_refresh_schedule
        for sig in list(self._prop_refresh_signals or []):
            if slot is None:
                break
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._prop_refresh_signals = []
        self._prop_refresh_schedule = None
        self._prop_refresh_timer = None
        self._prop_refresh_wired = False

    def _on_export_to_table(self) -> None:
        if not self._multi_conf_blocks_b64:
            return
        web = getattr(self, "_standalone_web", None)
        if web is None or self._btn_export_table is None:
            self._set_viewer_status("Export failed: 3D viewer is not available.")
            return
        self._btn_export_table.setEnabled(False)
        self._set_viewer_status("Exporting to table…")

        def _finish(state) -> None:
            try:
                self._export_conformers_to_table(state)
            finally:
                try:
                    self._btn_export_table.setEnabled(True)
                except Exception:
                    pass

        try:
            web.page().runJavaScript(
                "window.molmanagerConfState ? molmanagerConfState() : null",
                _finish,
            )
        except Exception:
            self._btn_export_table.setEnabled(True)
            self._set_viewer_status("Export failed: could not read the current conformer index.")

    def _export_conformers_to_table(self, state) -> None:
        app = self._host_app()
        export_fn = (
            getattr(app, "export_conformer_viewer_to_table", None) if app is not None else None
        )
        if not callable(export_fn):
            self._set_viewer_status(
                "Export failed: open the viewer from the main MolManager window."
            )
            return
        idx = 0
        superposed = False
        n = 0
        if isinstance(state, dict):
            try:
                idx = int(state.get("idx", 0))
            except Exception:
                idx = 0
            superposed = bool(state.get("superposed"))
            try:
                n = int(state.get("n", 0))
            except Exception:
                n = 0
        if superposed or n <= 1:
            if self._only_selected_in_3d():
                selected = self._selected_conf_indices()
                indices = selected if selected else None
            else:
                indices = None
        else:
            indices = [max(0, idx)]
        try:
            n_added = int(
                export_fn(
                    blocks_json_b64=self._multi_conf_blocks_b64,
                    conf_indices=indices,
                    strain_overlay=self._strain_overlay,
                    parent_oid=self._export_parent_oid,
                    confs_column=self._export_confs_column,
                )
            )
        except Exception as exc:
            logger.exception("Export to table failed")
            self._set_viewer_status(f"Export failed: {exc}")
            return
        if n_added <= 0:
            self._set_viewer_status("No conformers were exported.")
            return
        self._set_viewer_status(f"Added {n_added} row(s) to the table.")

    def _on_standalone_viewer_ready(self, web) -> None:
        if self._multi_conf_blocks_b64 and (self._only_selected_in_3d() or self._conf_superposed):
            self._refresh_3d_from_scope()
        else:
            self._sync_conf_legend()
        self._refit_standalone_viewer(web, zoom=True)
        QTimer.singleShot(200, lambda w=web: self._refit_standalone_viewer(w, zoom=True))

    def _refit_standalone_viewer(self, web, *, zoom: bool = False) -> None:
        """Resize the WebGL canvas; zoom only on first load, not on every Qt resize."""
        if web is None:
            return
        js = (
            "if (window.molmanagerRefit) { molmanagerRefit({zoom: "
            + ("true" if zoom else "false")
            + "}); }"
        )
        try:
            web.page().runJavaScript(js)
        except Exception:
            pass
        if zoom and int(web.width()) >= 80 and int(web.height()) >= 80:
            self._web_did_initial_zoom = True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        web = getattr(self, "_standalone_web", None)
        # After the first zoom, the page's resize scheduler keeps the canvas sized.
        if web is None or getattr(self, "_web_did_initial_zoom", False):
            return
        size = (int(web.width()), int(web.height()))
        if size == getattr(self, "_web_refit_size", None):
            return
        self._web_refit_size = size
        QTimer.singleShot(80, lambda w=web, s=size: self._refit_after_resize(w, s))

    def _refit_after_resize(self, web, size: tuple[int, int]) -> None:
        if getattr(self, "_web_refit_size", None) != size:
            return
        w, h = size
        first = not getattr(self, "_web_did_initial_zoom", False) and w >= 80 and h >= 80
        if first:
            self._web_did_initial_zoom = True
        self._refit_standalone_viewer(web, zoom=first)
