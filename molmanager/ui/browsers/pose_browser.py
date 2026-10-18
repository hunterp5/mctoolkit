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

"""Docked-pose browser: Data → Browser chrome around a ligand 3D preview."""

from __future__ import annotations

from typing import Any

from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...conformers.conformer_column_codec import is_packed_ensemble_header
from ...table.structure_depiction_layout import BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH
from ...docking.pose_file_io import (
    dock_result_headers,
    ordered_dock_pose_groups,
    pose_table_props,
    stamp_pose_parent_oids,
    write_pose_mols_sdf,
)
from ...services.column_labels import COLUMN_PARENT_OID
from ...chem.molecule_conversion import safe_float
from ..dock_complex_viewer import RENDER_STYLE_CHOICES, DockComplexEmbedView
from ..dockable_plot import (
    _GLYPH_BTN_SIZE,
    add_centered_browser_nav,
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_plot_options_button,
    make_plot_options_dialog,
    make_send_window_button,
    request_close_plot_widget,
    show_plot_options_dialog,
    style_browser_nav_buttons,
    style_plot_footer_text_button,
    sync_footer_on_parent_change,
)
from ..widgets import NumericTableWidgetItem
from .chrome import (
    BrowserHostDialog,
    apply_browser_body_layout,
    floating_browser_minimum_width,
    install_browser_nav_shortcuts,
    style_browser_data_table,
    style_browser_preview_host,
)

_ROW_TABLE_ROW_HEIGHT = 28
_TABLE_MAX_VISIBLE_ROWS = 8
_ROW_TABLE_MIN_COL_WIDTH = 72
POSE_ID_HEADER = "Pose"
_SKIP_HEADERS = frozenset({"ID_HIDDEN", "Structure", "SMILES", POSE_ID_HEADER})
_SCORE_KEYS = ("minimizedAffinity", "CNNaffinity", "CNNscore")


def pose_browser_headers(mols: list) -> list[str]:
    """Visible pose columns: unique Pose id, then scores (no SMILES or hidden fields)."""
    tail = [
        h
        for h in dock_result_headers(mols or [])
        if h not in _SKIP_HEADERS and not is_packed_ensemble_header(h)
    ]
    return [POSE_ID_HEADER, *tail]


def pose_browser_id(*, ligand: int, pose: int) -> str:
    """Unique 1-based pose id (``1.1`` is ligand 1, pose 1)."""
    return f"{max(1, int(ligand) + 1)}.{max(1, int(pose) + 1)}"


def parent_oid_from_mol(mol: Chem.Mol | None) -> int | None:
    """Return the table Parent OID stamped on a docked pose, if any."""
    if mol is None:
        return None
    raw = (pose_table_props(mol).get(COLUMN_PARENT_OID) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def pose_status_caption(mol: Chem.Mol | None, index: int, total: int) -> str:
    """Status line for Protein Viewer overlay and the 3D pane."""
    parts = [f"Dock pose {index} of {total}" if total else "Dock pose"]
    if mol is None:
        return parts[0]
    for key in _SCORE_KEYS:
        try:
            val = (mol.GetProp(key) or "").strip() if mol.HasProp(key) else ""
        except Exception:
            val = ""
        if val:
            parts.append(f"{key} {val}")
            break
    return "  ·  ".join(parts)


class PoseBrowserWidget(QWidget):
    """Browse docked ligands; the table lists every pose for the current ligand."""

    dockable_in_workspace = False
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = "Pose Browser"
        self._run_title = "Pose Browser"
        self._mols: list[Chem.Mol] = []
        self._all_mols: list[Chem.Mol] = []
        self._all_groups: list[list[Chem.Mol]] = []
        self._groups: list[list[Chem.Mol]] = []
        self._group_idx = 0
        self._idx = 0
        self._headers: list[str] = []
        self._receptor_path: str | None = None
        self._crystal_path: str | None = None
        self._table_oids: dict[int, int] = {}
        self._connected_selection_store = None
        self._filling_table = False
        self._sort_header: str | None = None
        self._sort_order = Qt.DescendingOrder

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._cb_only_selected = QCheckBox("Browse Selected")
        self._cb_only_selected.setToolTip(
            "When checked, navigation walks only ligands whose parent row is selected.\n"
            "When unchecked, it walks every docked ligand from the last run."
        )

        self._preview_host = QWidget(self)
        self._preview_host.setMinimumSize(360, 260)
        self._preview_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        style_browser_preview_host(self._preview_host, canvas=False)
        self._preview_ly = QVBoxLayout(self._preview_host)
        self._preview_ly.setContentsMargins(0, 0, 0, 0)
        self._preview_ly.setSpacing(0)
        self._viewer = DockComplexEmbedView(self._preview_host)
        self._viewer.setMinimumSize(0, 0)
        self._viewer.setMinimumWidth(0)
        self._viewer.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._preview_ly.addWidget(self._viewer, 1)
        root.addWidget(self._preview_host, 1)

        self._options_host = QWidget(self)
        options_ly = QVBoxLayout(self._options_host)
        options_ly.setContentsMargins(0, 0, 0, 0)
        options_ly.setSpacing(0)
        self._row_table = QTableWidget(0, 0, self._options_host)
        self._row_table.setObjectName("BrowserRowTable")
        self._row_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._row_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._row_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._row_table.setFocusPolicy(Qt.ClickFocus)
        self._row_table.setToolTip("Click a column header to sort from highest to lowest.")
        self._row_table.verticalHeader().setVisible(False)
        hdr = self._row_table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setSectionsClickable(True)
        hdr.sectionClicked.connect(self._on_pose_header_clicked)
        self._row_table.setSortingEnabled(False)
        hdr.setSortIndicatorShown(True)
        hdr.setSortIndicator(-1, Qt.DescendingOrder)
        self._row_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self._row_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._row_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._row_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._row_table.setWordWrap(False)
        self._row_table.setShowGrid(True)
        self._row_table.verticalHeader().setDefaultSectionSize(_ROW_TABLE_ROW_HEIGHT)
        self._row_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        style_browser_data_table(self._row_table)
        options_ly.addWidget(self._row_table)
        bar = self._row_table.horizontalScrollBar()
        if bar is not None:
            bar.rangeChanged.connect(lambda *_a: self._fit_row_table_height())
        self._fit_row_table_height()
        root.addWidget(self._options_host)
        self._options_visible = True

        self._nav_bar = QWidget(self)
        self._nav_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row_btns = QHBoxLayout(self._nav_bar)
        row_btns.setContentsMargins(0, 0, 0, 0)
        row_btns.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First docked ligand (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous docked ligand (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next docked ligand (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last docked ligand (End)")
        self._btn_toggle_select = QPushButton()
        self._btn_toggle_select.setToolTip("Select this ligand in the compound table")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
            self._btn_toggle_select,
            select_checkable=True,
        )
        add_centered_browser_nav(
            row_btns,
            [
                self._btn_first,
                self._btn_back,
                self._btn_fwd,
                self._btn_last,
                self._btn_toggle_select,
            ],
            trailing=self._cb_only_selected,
        )
        root.addWidget(self._nav_bar)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._footer_bar.setMinimumHeight(_GLYPH_BTN_SIZE)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)

        self._header_left = QWidget(self._footer_bar)
        self._header_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left_ly = QHBoxLayout(self._header_left)
        left_ly.setContentsMargins(0, 0, 0, 0)
        left_ly.setSpacing(4)
        self._opts_btn = make_plot_options_button(
            self,
            tooltip="Pose Browser settings: scores table, render styles, and save.",
        )
        self._opts_btn.clicked.connect(self._open_browser_options)
        left_ly.addWidget(self._opts_btn)
        left_ly.addStretch(1)

        self._meta = QLabel(self._footer_bar)
        self._meta.setAlignment(Qt.AlignCenter)
        self._meta.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._meta.setMinimumHeight(_GLYPH_BTN_SIZE)

        self._header_right = QWidget(self._footer_bar)
        self._header_right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_ly = QHBoxLayout(self._header_right)
        right_ly.setContentsMargins(0, 0, 0, 0)
        right_ly.setSpacing(4)
        right_ly.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this browser in the Protein Viewer Manager.",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        right_ly.addWidget(self._add_to_main_btn)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked browser in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        right_ly.addWidget(self._send_window_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.setToolTip("Close this browser.")
        self._close_btn.clicked.connect(self._close_docked_browser)
        style_plot_footer_text_button(self._close_btn)
        right_ly.addWidget(self._close_btn)

        foot.addWidget(self._header_left, 1)
        foot.addWidget(self._meta, 0)
        foot.addWidget(self._header_right, 1)
        self._apply_header_caption_font()
        root.insertWidget(0, self._footer_bar)

        self._opts_panel = QWidget(self)
        opts_form = QFormLayout(self._opts_panel)
        opts_form.setContentsMargins(0, 0, 0, 0)
        opts_form.setHorizontalSpacing(10)
        opts_form.setVerticalSpacing(8)
        self._cb_hide_options = QCheckBox("Hide Options")
        self._cb_hide_options.setToolTip(
            "Hide the pose score table so only the 3D preview and navigation controls are shown."
        )
        self._cb_hide_options.toggled.connect(self._on_hide_options_toggled)
        opts_form.addRow(self._cb_hide_options)
        self._render_combos: dict[str, QComboBox] = {}
        ligand_choices = RENDER_STYLE_CHOICES.get("ligand", ())
        cb = QComboBox(self._opts_panel)
        for style_id, label in ligand_choices:
            cb.addItem(label, style_id)
        idx = next((i for i, (sid, _lab) in enumerate(ligand_choices) if sid == "ballstick"), 0)
        cb.setCurrentIndex(idx)
        cb.currentIndexChanged.connect(lambda _i: self._on_render_combo_changed("ligand"))
        opts_form.addRow("Ligand:", cb)
        self._render_combos["ligand"] = cb
        self._btn_save = QPushButton("Save poses…", self._opts_panel)
        self._btn_save.setToolTip("Write the current docking poses to an SDF file.")
        self._btn_save.clicked.connect(self._save_poses)
        opts_form.addRow(self._btn_save)
        self._btn_add_pose = QPushButton("Add pose to Viewer", self._opts_panel)
        self._btn_add_pose.setToolTip(
            "Pin the current docked pose into Protein Viewer Manager. The crystal ligand stays visible."
        )
        self._btn_add_pose.clicked.connect(self._add_current_pose_to_viewer)
        opts_form.addRow(self._btn_add_pose)
        self._btn_add_all_poses = QPushButton("Add all poses to Viewer", self._opts_panel)
        self._btn_add_all_poses.setToolTip(
            "Pin every pose for the current ligand into Protein Viewer Manager."
        )
        self._btn_add_all_poses.clicked.connect(self._add_all_poses_to_viewer)
        opts_form.addRow(self._btn_add_all_poses)
        self._opts_dialog = make_plot_options_dialog(
            self,
            self._opts_panel,
            title="Pose Browser Settings",
            min_width=320,
            min_height=220,
        )

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_toggle_select.clicked.connect(self._toggle_current_row_selected)
        self._cb_only_selected.toggled.connect(self._on_only_selected_toggled)
        self._row_table.itemSelectionChanged.connect(self._on_pose_row_selected)

        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )

        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(80)
        self._selection_timer.timeout.connect(self._refresh_selected_scope)

        self._sync_footer_chrome()
        self._sync_options_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())
        self._connect_table_selection()
        self._wire_pose_browser_destroyed()
        self._update_ui()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().showEvent(event)
        if getattr(self, "_mols", None) and getattr(self, "_viewer", None) is not None:
            self._sync_pose_views()

    def _wire_pose_browser_destroyed(self) -> None:
        app = self._app
        if app is None:
            return
        slot = getattr(app, "_on_pose_browser_widget_destroyed", None)
        if not callable(slot):
            return
        try:
            self.destroyed.disconnect(slot)
        except TypeError:
            pass
        self.destroyed.connect(slot)

    def on_docked_plot_closing(self) -> None:
        """Drop the Protein Viewer overlay as soon as this docked panel is closed."""
        app = self._app
        clearer = getattr(app, "_clear_protein_viewer_dock_pose", None) if app is not None else None
        if callable(clearer):
            clearer()

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self._disconnect_table_selection()
        self.parent_app = parent_app
        self._app = parent_app
        self._connect_table_selection()
        self._wire_pose_browser_destroyed()
        self._refresh_row_table()

    def embedded_minimum_width(self) -> int:
        return max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), self.floating_content_minimum_width())

    def floating_content_minimum_width(self) -> int:
        """Width needed for footer + nav chrome without clipping."""
        return floating_browser_minimum_width(self, floor=self.embedded_minimum_width())

    def create_floating_dialog(self, parent_app) -> "PoseBrowserDialog":
        self.show()
        return PoseBrowserDialog(parent_app, panel=self)

    def set_poses(
        self,
        mols: list,
        *,
        title: str = "Pose Browser",
        receptor_path: str | None = None,
        crystal_path: str | None = None,
    ) -> None:
        """Replace the browsable pose list. The 3D pane shows the ligand pose only."""
        self._window_title = "Pose Browser"
        self._run_title = str(title or "Pose Browser")
        self._all_mols = [m for m in (mols or []) if m is not None]
        self._table_oids = {}
        self._headers = pose_browser_headers(self._all_mols)
        self._receptor_path = (receptor_path or "").strip() or None
        self._crystal_path = (crystal_path or "").strip() or None
        known = self._known_table_oids()
        stamp_pose_parent_oids(self._all_mols, known)
        has_parent = any(parent_oid_from_mol(m) is not None for m in self._all_mols)
        self._cb_only_selected.setEnabled(has_parent)
        if not has_parent and self._cb_only_selected.isChecked():
            self._cb_only_selected.blockSignals(True)
            self._cb_only_selected.setChecked(False)
            self._cb_only_selected.blockSignals(False)
        app = self._app
        if app is not None:
            app._dock_pose_zoomed = False
            status = getattr(app, "status_label", None)
            if status is not None and self._run_title and self._run_title != "Pose Browser":
                status.setText(self._run_title)
        self._apply_pose_scope(preserve_index=False)
        dlg = self.window()
        if isinstance(dlg, PoseBrowserDialog):
            dlg.setWindowTitle(self._window_title)

    def set_pose_index(self, index: int) -> None:
        """Jump to a pose in the current ligand's table."""
        group = self._current_group()
        if not group:
            return
        self._idx = max(0, min(int(index), len(group) - 1))
        self._update_ui()

    def current_mol(self) -> Chem.Mol | None:
        group = self._current_group()
        if not group or not (0 <= self._idx < len(group)):
            return None
        return group[self._idx]

    def _current_group(self) -> list[Chem.Mol]:
        if not self._groups or not (0 <= self._group_idx < len(self._groups)):
            return []
        return self._groups[self._group_idx]

    def _ligand_index_for_group(self, group: list[Chem.Mol]) -> int:
        for i, item in enumerate(self._all_groups):
            if item is group:
                return i
        try:
            return self._all_groups.index(group)
        except ValueError:
            return self._group_idx

    def _known_table_oids(self) -> set[int]:
        app = self._app
        model = getattr(app, "_table_model", None) if app is not None else None
        if model is None:
            return set()
        known: set[int] = set()
        try:
            n = int(model.rowCount())
        except Exception:
            return set()
        for row in range(n):
            try:
                known.add(int(model.row_oid(row)))
            except Exception:
                continue
        return known

    def _group_parent_oid(self, group: list[Chem.Mol] | None) -> int | None:
        for mol in group or []:
            oid = parent_oid_from_mol(mol)
            if oid is not None:
                return oid
        return None

    def _add_to_main_window(self) -> None:
        app = self.parent_app
        if app is None:
            return
        protein_fn = getattr(app, "_live_protein_viewer", None)
        protein = protein_fn() if callable(protein_fn) else None
        if protein is None:
            opener = getattr(app, "open_protein_viewer", None)
            if callable(opener):
                protein = opener()
        dock = getattr(protein, "dock_side_widget", None) if protein is not None else None
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, PoseBrowserDialog):
            discard_host_dialog_after_dock(dlg, app, "_pose_browser_dialog")
        self._sync_footer_chrome()

    def _send_to_new_window(self) -> None:
        protein = self._live_protein_viewer()
        if protein is not None and protein.is_side_docked(self):
            protein.undock_side_widget(self)
            dlg = self.create_floating_dialog(self.parent_app)
            app = self.parent_app
            if app is not None:
                setattr(app, "_pose_browser_dialog", dlg)
                slot = getattr(app, "_on_pose_browser_dialog_destroyed", None)
                if callable(slot):
                    try:
                        dlg.destroyed.disconnect(slot)
                    except TypeError:
                        pass
                    dlg.destroyed.connect(slot)
            dlg.show()
            self._sync_footer_chrome()
            return
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_browser(self) -> None:
        protein = self._live_protein_viewer()
        closer = getattr(protein, "close_side_dock_widget", None) if protein is not None else None
        if callable(closer) and closer(self):
            return
        request_close_plot_widget(
            self,
            title="Close Browser",
            message="Close this browser?",
        )

    def _live_protein_viewer(self):
        app = self.parent_app
        finder = getattr(app, "_live_protein_viewer", None) if app is not None else None
        return finder() if callable(finder) else None

    def _is_docked_in_viewer(self) -> bool:
        protein = self._live_protein_viewer()
        check = getattr(protein, "is_side_docked", None) if protein is not None else None
        return callable(check) and bool(check(self))

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return False

    def _apply_header_caption_font(self) -> None:
        meta = getattr(self, "_meta", None)
        if meta is None:
            return
        font = None
        table = getattr(self._app, "table", None) if self._app is not None else None
        if table is not None:
            header = table.horizontalHeader()
            if header is not None:
                try:
                    font = QFont(header.font())
                except RuntimeError:
                    font = None
        if font is None:
            font = QFont(self.font())
        meta.setFont(font)

    def _sync_footer_chrome(self) -> None:
        from ..dockable_plot import apply_plot_chrome_glyphs, sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        self._apply_header_caption_font()
        floating = isinstance(self.window(), PoseBrowserDialog)
        docked = self._is_docked_in_viewer() or self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)
        if floating:
            dlg = self.window()
            ensure = getattr(dlg, "ensure_fits_chrome", None)
            if callable(ensure):
                ensure()

    def _sync_options_chrome(self) -> None:
        visible = bool(getattr(self, "_options_visible", True))
        host = getattr(self, "_options_host", None)
        if host is not None:
            host.setVisible(visible)
        cb = getattr(self, "_cb_hide_options", None)
        if cb is not None and cb.isChecked() == visible:
            cb.blockSignals(True)
            cb.setChecked(not visible)
            cb.blockSignals(False)

    def _on_hide_options_toggled(self, checked: bool) -> None:
        self._options_visible = not bool(checked)
        self._sync_options_chrome()

    def _open_browser_options(self) -> None:
        show_plot_options_dialog(getattr(self, "_opts_dialog", None))

    def _on_render_combo_changed(self, component: str) -> None:
        cb = self._render_combos.get(component)
        if cb is None:
            return
        style = cb.currentData()
        setter = getattr(self._viewer, "set_render_style", None)
        if callable(setter) and style:
            setter(str(component), str(style))

    def _save_poses(self) -> None:
        mols = list(self._all_mols)
        if not mols:
            QMessageBox.information(self, "Pose Browser", "No poses to save.")
            return
        path, _sel = QFileDialog.getSaveFileName(
            self,
            "Save poses",
            "",
            "SDF (*.sdf *.sd);;All files (*.*)",
        )
        if not path:
            return
        try:
            n = write_pose_mols_sdf(mols, path)
        except Exception as exc:
            QMessageBox.warning(self, "Pose Browser", f"Could not save poses:\n{exc}")
            return
        app = self._app
        status = getattr(app, "status_label", None) if app is not None else None
        if status is not None:
            status.setText(f"Saved {n} pose(s).")

    def _protein_viewer_for_poses(self):
        """Open Protein Viewer if needed and load receptor/crystal when it is empty."""
        app = self._app
        if app is None:
            QMessageBox.information(
                self,
                "Protein Viewer",
                "Open Protein Viewer from the main window first.",
            )
            return None
        opener = getattr(app, "open_protein_viewer", None)
        dlg = opener() if callable(opener) else None
        if dlg is None:
            live = getattr(app, "_live_protein_viewer", None)
            dlg = live() if callable(live) else None
        if dlg is None:
            QMessageBox.information(self, "Protein Viewer", "Could not open Protein Viewer.")
            return None
        prepare = getattr(app, "_prepare_protein_viewer_for_poses", None)
        if callable(prepare) and not getattr(dlg, "_slots", None):
            prepare(dlg, self._receptor_path, crystal_path=self._crystal_path)
        return dlg

    def _add_current_pose_to_viewer(self) -> None:
        mol = self.current_mol()
        if mol is None:
            QMessageBox.information(self, "Protein Viewer", "No pose to add.")
            return
        dlg = self._protein_viewer_for_poses()
        if dlg is None:
            return
        from ..dock_complex_viewer import pose_manager_slot_name

        adder = getattr(dlg, "add_ligand_mol", None)
        name = pose_manager_slot_name(mol, self._idx + 1)
        if not callable(adder) or not adder(mol, name=name, refit=False):
            QMessageBox.warning(self, "Protein Viewer", "Could not add that pose to the Manager.")
            return
        app = self._app
        status = getattr(app, "status_label", None) if app is not None else None
        if status is not None:
            status.setText(f"Added {Path(name).stem} to Protein Viewer.")

    def _add_all_poses_to_viewer(self) -> None:
        mols = list(self._mols)
        if not mols:
            QMessageBox.information(self, "Protein Viewer", "No poses to add.")
            return
        dlg = self._protein_viewer_for_poses()
        if dlg is None:
            return
        adder = getattr(dlg, "add_dock_pose_mols", None)
        n = adder(mols) if callable(adder) else 0
        if not n:
            QMessageBox.warning(self, "Protein Viewer", "Could not add poses to the Manager.")
            return
        app = self._app
        status = getattr(app, "status_label", None) if app is not None else None
        if status is not None:
            status.setText(f"Added {n} pose(s) to Protein Viewer.")

    def event(self, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        return super().event(event)

    def _go_first(self) -> None:
        self._group_idx = 0
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._group_idx = max(0, len(self._groups) - 1)
        self._idx = 0
        self._update_ui()

    def _step(self, delta: int) -> None:
        n = len(self._groups)
        if n <= 1:
            return
        self._group_idx = (self._group_idx + int(delta)) % n
        self._idx = 0
        self._update_ui()

    def _on_only_selected_toggled(self, _checked: bool = False) -> None:
        self._apply_pose_scope(preserve_index=True)

    def _selected_oids(self) -> frozenset[int]:
        store = self._selection_store_or_none()
        return store.oids if store is not None else frozenset()

    def _selection_store_or_none(self):
        return getattr(self._app, "selection_store", None) if self._app is not None else None

    def _apply_pose_scope(self, *, preserve_index: bool) -> None:
        cur = self.current_mol() if preserve_index else None
        known = self._known_table_oids()
        stamp_pose_parent_oids(self._all_mols, known)
        self._all_groups = ordered_dock_pose_groups(self._all_mols, known)
        groups = list(self._all_groups)
        if self._cb_only_selected.isChecked():
            selected = self._selected_oids()
            groups = [g for g in groups if self._group_parent_oid(g) in selected]
        self._groups = groups
        self._group_idx = 0
        self._idx = 0
        if cur is not None:
            for gi, group in enumerate(self._groups):
                for pi, mol in enumerate(group):
                    if mol is cur:
                        self._group_idx = gi
                        self._idx = pi
                        break
                else:
                    continue
                break
        self._mols = self._current_group()
        self._refresh_row_table()
        self._update_ui()

    def _connect_table_selection(self) -> None:
        self._disconnect_table_selection()
        store = self._selection_store_or_none()
        if store is None:
            return
        store.changed.connect(self._on_table_selection_changed)
        self._connected_selection_store = store

    def _disconnect_table_selection(self) -> None:
        store = getattr(self, "_connected_selection_store", None)
        if store is None:
            return
        try:
            store.changed.disconnect(self._on_table_selection_changed)
        except (TypeError, RuntimeError):
            pass
        self._connected_selection_store = None

    def _on_table_selection_changed(self, origin: object = None) -> None:
        if origin is self:
            return
        self._sync_select_button()
        if not self._cb_only_selected.isChecked():
            return
        timer = getattr(self, "_selection_timer", None)
        if timer is not None:
            timer.start()

    def _refresh_selected_scope(self) -> None:
        if self._cb_only_selected.isChecked():
            self._apply_pose_scope(preserve_index=True)

    def _all_mol_index(self, mol: Chem.Mol | None) -> int | None:
        if mol is None:
            return None
        for i, item in enumerate(self._all_mols):
            if item is mol:
                return i
        return None

    def _target_table_oid(self, mol: Chem.Mol | None) -> int | None:
        parent = parent_oid_from_mol(mol)
        if parent is not None:
            return parent
        idx = self._all_mol_index(mol)
        if idx is None:
            return None
        return self._table_oids.get(idx)

    def _append_pose_to_table(self, mol: Chem.Mol) -> int | None:
        app = self._app
        if app is None:
            return None
        ensure = getattr(app, "_ensure_columns", None)
        cols = [h for h in pose_browser_headers([mol]) if h not in {"Structure", POSE_ID_HEADER}]
        if callable(ensure) and cols:
            ensure(cols)
        try:
            oid = int(app.next_oid)
            app.next_oid = oid + 1
        except Exception:
            return None
        ingest = getattr(app, "_ingest_store_mol", None)
        model = getattr(app, "_table_model", None)
        if not callable(ingest) or model is None:
            return None
        try:
            stored = Chem.Mol(mol)
        except Exception:
            stored = mol
        cells = ingest(oid, stored)
        model.append_rows_batch([(oid, cells)])
        render = getattr(app, "start_render_worker", None)
        live = getattr(app, "mols", {}).get(oid) if app is not None else None
        if callable(render) and live is not None:
            render(oid, live, skip_mol_props=True)
        return oid

    def _toggle_current_row_selected(self) -> None:
        mol = self.current_mol()
        app = self._app
        if mol is None or app is None:
            return
        oid = self._target_table_oid(mol)
        if oid is None:
            idx = self._all_mol_index(mol)
            oid = self._append_pose_to_table(mol)
            if oid is None:
                return
            if idx is not None:
                self._table_oids[idx] = oid
        app.select_table_oids(self._selected_oids() ^ {oid}, origin=self, reveal=False)
        self._sync_select_button()
        if self._cb_only_selected.isChecked():
            self._selection_timer.start()

    def _fit_row_table_height(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        n_rows = max(1, min(int(table.rowCount() or 1), _TABLE_MAX_VISIBLE_ROWS))
        hdr_h = int(table.horizontalHeader().sizeHint().height())
        frame = 2 * int(table.frameWidth())
        style = table.style()
        extent = int(style.pixelMetric(QStyle.PM_ScrollBarExtent, None, table))
        hbar = table.horizontalScrollBar()
        hinted = int(hbar.sizeHint().height()) if hbar is not None else 0
        h_scroll = max(extent, hinted, 16)
        v_scroll = extent if int(table.rowCount() or 0) > _TABLE_MAX_VISIBLE_ROWS else 0
        table.setFixedHeight(
            hdr_h + n_rows * _ROW_TABLE_ROW_HEIGHT + frame + h_scroll + v_scroll + 4
        )

    def _refresh_row_table(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        names = list(self._headers)
        table.blockSignals(True)
        table.setColumnCount(len(names))
        table.setHorizontalHeaderLabels(names)
        table.blockSignals(False)
        self._fill_row_table()

    def _pose_table_item(self, text: str, pose_idx: int) -> QTableWidgetItem:
        raw = (text or "").strip()
        num = safe_float(raw)
        if num is not None:
            item = NumericTableWidgetItem()
            item.setData(Qt.EditRole, num)
            item.setText(raw)
        else:
            item = QTableWidgetItem(raw)
        item.setData(Qt.UserRole, int(pose_idx))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        if raw:
            item.setToolTip(raw)
        return item

    def _size_pose_table_columns(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        table.resizeColumnsToContents()
        for col in range(table.columnCount()):
            width = max(int(table.columnWidth(col)) + 12, _ROW_TABLE_MIN_COL_WIDTH)
            table.setColumnWidth(col, width)

    def _sort_column_index(self) -> int:
        name = self._sort_header
        if not name:
            return -1
        for i, header in enumerate(self._headers):
            if header == name:
                return i
        return -1

    def _apply_pose_table_sort(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        hdr = table.horizontalHeader()
        hdr.setSortIndicatorShown(True)
        col = self._sort_column_index()
        if col < 0 or table.rowCount() <= 0:
            hdr.setSortIndicator(-1, Qt.DescendingOrder)
            self._select_current_pose_row()
            return
        hdr.setSortIndicator(col, self._sort_order)
        table.sortItems(col, self._sort_order)
        self._select_current_pose_row()

    def _on_pose_header_clicked(self, logical: int) -> None:
        table = getattr(self, "_row_table", None)
        if table is None or logical < 0 or logical >= table.columnCount():
            return
        item = table.horizontalHeaderItem(int(logical))
        name = item.text() if item is not None else ""
        if not name and 0 <= logical < len(self._headers):
            name = self._headers[logical]
        if not name:
            return
        if self._sort_header == name:
            self._sort_order = (
                Qt.AscendingOrder if self._sort_order == Qt.DescendingOrder else Qt.DescendingOrder
            )
        else:
            self._sort_header = name
            self._sort_order = Qt.DescendingOrder
        self._filling_table = True
        table.blockSignals(True)
        try:
            self._apply_pose_table_sort()
        finally:
            table.blockSignals(False)
            self._filling_table = False

    def _pose_index_for_table_row(self, row: int) -> int | None:
        table = getattr(self, "_row_table", None)
        if table is None or row < 0:
            return None
        item = None
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None:
                break
        if item is None:
            return None
        try:
            idx = int(item.data(Qt.UserRole))
        except (TypeError, ValueError):
            return None
        group = self._current_group()
        if not group or not (0 <= idx < len(group)):
            return None
        return idx

    def _select_current_pose_row(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        group = self._current_group()
        if not group or not (0 <= self._idx < len(group)):
            table.clearSelection()
            return
        for row in range(table.rowCount()):
            if self._pose_index_for_table_row(row) == self._idx:
                table.selectRow(row)
                return
        table.clearSelection()

    def _fill_row_table(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        group = self._current_group()
        self._filling_table = True
        table.blockSignals(True)
        hdr = table.horizontalHeader()
        hdr.blockSignals(True)
        try:
            table.setRowCount(len(group))
            ligand_idx = self._ligand_index_for_group(group)
            for row, mol in enumerate(group):
                props = pose_table_props(mol)
                for col, name in enumerate(self._headers):
                    if name == POSE_ID_HEADER:
                        text = pose_browser_id(ligand=ligand_idx, pose=row)
                    else:
                        text = props.get(name) or ""
                    table.setItem(row, col, self._pose_table_item(text, row))
                table.setRowHeight(row, _ROW_TABLE_ROW_HEIGHT)
            self._size_pose_table_columns()
            self._apply_pose_table_sort()
        finally:
            hdr.blockSignals(False)
            table.blockSignals(False)
            self._filling_table = False
        self._fit_row_table_height()

    def _on_pose_row_selected(self) -> None:
        if self._filling_table:
            return
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        sm = table.selectionModel()
        rows = sm.selectedRows() if sm is not None else []
        if not rows:
            return
        pose_idx = self._pose_index_for_table_row(int(rows[0].row()))
        if pose_idx is None:
            return
        if pose_idx == self._idx:
            return
        self._idx = pose_idx
        self._mols = self._current_group()
        self._sync_caption()
        self._sync_select_button()
        self._sync_pose_views()

    def _sync_select_button(self) -> None:
        mol = self.current_mol()
        if mol is None:
            self._btn_toggle_select.setEnabled(False)
            self._btn_toggle_select.setChecked(False)
            self._btn_toggle_select.setToolTip("Select this ligand in the compound table")
            return
        self._btn_toggle_select.setEnabled(True)
        oid = self._target_table_oid(mol)
        store = self._selection_store_or_none()
        selected = bool(oid is not None and store is not None and store.contains(oid))
        self._btn_toggle_select.setChecked(selected)
        if oid is None:
            self._btn_toggle_select.setToolTip("Add this pose to the compound table")
        elif selected:
            self._btn_toggle_select.setToolTip("Deselect this ligand in the table")
        else:
            self._btn_toggle_select.setToolTip("Select this ligand in the table")

    def _sync_caption(self) -> None:
        n_groups = len(self._groups)
        group = self._current_group()
        n_poses = len(group)
        if n_groups == 0 or n_poses == 0:
            self._meta.setText("No poses to browse.")
            return
        scope = "Selected ligands" if self._cb_only_selected.isChecked() else "Ligands"
        self._meta.setText(
            f"{scope}: {self._group_idx + 1} / {n_groups}  ·  Pose {self._idx + 1} / {n_poses}"
        )

    def _sync_pose_views(self) -> None:
        mol = self.current_mol()
        setter = getattr(self._viewer, "set_ligand_mol", None)
        if callable(setter):
            setter(mol)
        app = self._app
        if app is None:
            return
        protein = getattr(app, "_live_protein_viewer", None)
        dlg = protein() if callable(protein) else None
        if dlg is None:
            return
        caption = pose_status_caption(mol, self._idx + 1, len(self._current_group()))
        sync = getattr(app, "_sync_protein_viewer_dock_pose", None)
        if callable(sync):
            sync(mol, caption=caption)

    def _update_ui(self) -> None:
        n_groups = len(self._groups)
        self._mols = self._current_group()
        nav_on = n_groups > 1
        for btn in (self._btn_first, self._btn_back, self._btn_fwd, self._btn_last):
            btn.setEnabled(nav_on)
        if n_groups == 0:
            self._group_idx = 0
            self._idx = 0
            self._sync_caption()
            self._fill_row_table()
            self._sync_select_button()
            setter = getattr(self._viewer, "set_ligand_mol", None)
            if callable(setter):
                setter(None)
            app = self._app
            clear = (
                getattr(app, "_clear_protein_viewer_dock_pose", None) if app is not None else None
            )
            if callable(clear):
                clear()
            return
        self._group_idx = max(0, min(self._group_idx, n_groups - 1))
        group = self._current_group()
        self._mols = group
        self._idx = max(0, min(self._idx, max(0, len(group) - 1)))
        self._sync_caption()
        self._fill_row_table()
        self._sync_select_button()
        self._sync_pose_views()


class PoseBrowserDialog(BrowserHostDialog):
    """Floating window hosting a :class:`PoseBrowserWidget`."""

    default_title = "Pose Browser"
    panel_cls = PoseBrowserWidget
    fit_chrome = True
    sync_options_chrome = True

    def set_poses(
        self,
        mols: list,
        *,
        title: str = "Pose Browser",
        receptor_path: str | None = None,
        crystal_path: str | None = None,
    ) -> None:
        self.setWindowTitle(str(title or "Pose Browser"))
        self._panel.set_poses(
            mols, title=title, receptor_path=receptor_path, crystal_path=crystal_path
        )

    def _on_close_accepted(self) -> None:
        # Floating close hides this singleton without destroying it; drop the
        # Protein Viewer overlay immediately. Docked panels keep the overlay
        # until the widget itself is destroyed.
        if getattr(self, "_panel", None) is None:
            return
        app = self.parent_app
        clearer = getattr(app, "_clear_protein_viewer_dock_pose", None) if app is not None else None
        if callable(clearer):
            clearer()
