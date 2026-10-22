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

"""Selection browser panel: step through table rows with structure preview."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QEvent, QItemSelectionModel, QSize, Qt, QTimer
from PyQt5.QtGui import QBrush, QFont, QIcon, QImage, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ..compound_table_model import CompoundTableModel
from ..dockable_plot import (
    _GLYPH_BTN_SIZE,
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_plot_options_button,
    make_plot_options_dialog,
    make_send_window_button,
    request_close_plot_widget,
    show_plot_options_dialog,
    add_centered_browser_nav,
    style_browser_nav_buttons,
    style_plot_footer_text_button,
    sync_footer_on_parent_change,
)
from ..layout_perf import perf_span
from .chrome import (
    BrowserHostDialog,
    BrowserIndexSpinBox,
    apply_browser_body_layout,
    floating_browser_minimum_width,
    install_browser_nav_shortcuts,
    style_browser_data_table,
    style_browser_preview_host,
    style_browser_structure_label,
)

_ROW_TABLE_PIXMAP_MAX = QSize(48, 36)
_ROW_TABLE_ROW_HEIGHT = _ROW_TABLE_PIXMAP_MAX.height() + 8

BROWSER_PREVIEW_MODE_RDKIT_2D = "rdkit_2d"
BROWSER_PREVIEW_MODE_3DMOL_2D = "3dmol_2d"
BROWSER_PREVIEW_MODE_3DMOL_3D = "3dmol_3d"
BROWSER_PREVIEW_MODE_LABELS: tuple[tuple[str, str], ...] = (
    (BROWSER_PREVIEW_MODE_RDKIT_2D, "RDKit 2D"),
    (BROWSER_PREVIEW_MODE_3DMOL_2D, "3Dmol 2D"),
    (BROWSER_PREVIEW_MODE_3DMOL_3D, "3Dmol 3D"),
)
DEFAULT_BROWSER_PREVIEW_MODE = BROWSER_PREVIEW_MODE_RDKIT_2D


def _set_combo_current_data(combo: QComboBox, data) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            combo.setCurrentIndex(i)
            return


class SelectionBrowserWidget(QWidget):
    """Forward/back through the current selection or entire table; shows a structure preview."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = "Browser"

        self._rows: list[int] = []
        self._idx = 0
        self._preview_pix_cache: dict[
            tuple[int, int, int, int], QPixmap
        ] = {}  # (oid, w_px, h_px, depiction revision) -> pixmap

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._cb_only_selected = QCheckBox("Browse Selected")
        self._cb_only_selected.setToolTip(
            "When checked, Browser walks only the current selection.\n"
            "When unchecked, Browser walks the entire table."
        )

        self._preview_host = QWidget(self)
        self._preview_host.setMinimumSize(360, 260)
        # Ignored: preview content must not drive the window sizeHint (move/resize loop).
        self._preview_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        style_browser_preview_host(self._preview_host)
        self._preview_ly = QVBoxLayout(self._preview_host)
        self._preview_ly.setContentsMargins(0, 0, 0, 0)
        self._preview_ly.setSpacing(0)

        self._struct_label = QLabel(self._preview_host)
        self._struct_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        style_browser_structure_label(self._struct_label)
        self._preview_ly.addWidget(self._struct_label, 1)
        self._view_3d = None
        self._preview_mode = DEFAULT_BROWSER_PREVIEW_MODE
        root.addWidget(self._preview_host, 1)

        self._options_host = QWidget(self)
        options_ly = QVBoxLayout(self._options_host)
        options_ly.setContentsMargins(0, 0, 0, 0)
        options_ly.setSpacing(0)
        self._row_table = QTableWidget(0, 0, self._options_host)
        self._row_table.setObjectName("BrowserRowTable")
        self._row_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._row_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._row_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._row_table.setFocusPolicy(Qt.NoFocus)
        self._row_table.verticalHeader().setVisible(False)
        self._row_table.horizontalHeader().setHighlightSections(False)
        self._row_table.horizontalHeader().setStretchLastSection(True)
        self._row_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._row_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._row_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._row_table.setWordWrap(False)
        self._row_table.setShowGrid(True)
        self._row_table.setIconSize(_ROW_TABLE_PIXMAP_MAX)
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
        self._btn_first.setToolTip("First eligible row in scope (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous eligible row (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next eligible row (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last eligible row in scope (End)")
        self._btn_toggle_select = QPushButton()
        self._btn_toggle_select.setToolTip("Select or deselect this row in the table")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
            self._btn_toggle_select,
            select_checkable=True,
        )
        self._index_syncing = False
        self._index_host = QWidget(self._nav_bar)
        index_row = QHBoxLayout(self._index_host)
        index_row.setContentsMargins(0, 0, 10, 0)
        index_row.setSpacing(4)
        self._index_scope_label = QLabel("Row", self._index_host)
        self._index_scope_label.setAlignment(Qt.AlignVCenter)
        self._index_edit = BrowserIndexSpinBox(self._index_host)
        self._index_edit.setToolTip("Type a number and press Enter to jump to that row.")
        self._index_count_label = QLabel("/ 0", self._index_host)
        self._index_count_label.setAlignment(Qt.AlignVCenter)
        index_row.addWidget(self._index_scope_label)
        index_row.addWidget(self._index_edit)
        index_row.addWidget(self._index_count_label)
        self._index_edit.valueChanged.connect(self._on_index_edited)
        add_centered_browser_nav(
            row_btns,
            [
                self._btn_first,
                self._btn_back,
                self._btn_fwd,
                self._btn_last,
                self._btn_toggle_select,
            ],
            leading=self._index_host,
            trailing=self._cb_only_selected,
        )
        root.addWidget(self._nav_bar)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._footer_bar.setMinimumHeight(_GLYPH_BTN_SIZE)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)

        # Equal-stretch side strips keep the caption geometrically centered.
        self._header_left = QWidget(self._footer_bar)
        self._header_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left_ly = QHBoxLayout(self._header_left)
        left_ly.setContentsMargins(0, 0, 0, 0)
        left_ly.setSpacing(4)
        self._opts_btn = make_plot_options_button(
            self,
            tooltip="Browser settings: row table and structure view.",
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
            tooltip="Dock this browser beside the compound table.",
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
            "Hide the current-row table so only the structure preview and navigation "
            "controls are shown."
        )
        self._cb_hide_options.toggled.connect(self._on_hide_options_toggled)
        opts_form.addRow(self._cb_hide_options)
        self._preview_mode_combo = QComboBox()
        for key, label in BROWSER_PREVIEW_MODE_LABELS:
            self._preview_mode_combo.addItem(label, key)
        _set_combo_current_data(self._preview_mode_combo, DEFAULT_BROWSER_PREVIEW_MODE)
        self._preview_mode_combo.setToolTip(
            "How the current structure is drawn: RDKit 2D depiction, interactive 3Dmol 2D "
            "(flat), or interactive 3Dmol 3D. Existing 3D coordinates are kept in 3D mode "
            "when present."
        )
        self._preview_mode_combo.currentIndexChanged.connect(self._on_preview_mode_changed)
        opts_form.addRow("Structure view:", self._preview_mode_combo)
        self._opts_dialog = make_plot_options_dialog(
            self,
            self._opts_panel,
            title="Browser Settings",
            min_width=320,
            min_height=180,
        )

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_toggle_select.clicked.connect(self._toggle_current_row_selected)
        self._cb_only_selected.toggled.connect(lambda _v: self.refresh_from_app())

        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setSingleShot(True)
        self._auto_refresh_timer.setInterval(80)
        self._auto_refresh_timer.timeout.connect(
            lambda: self.refresh_from_app(preserve_position=True)
        )
        # Selection-only rescope: same coalescing, but previews are still valid.
        self._selection_refresh_timer = QTimer(self)
        self._selection_refresh_timer.setSingleShot(True)
        self._selection_refresh_timer.setInterval(80)
        self._selection_refresh_timer.timeout.connect(
            lambda: self.refresh_from_app(preserve_position=True, keep_previews=True)
        )

        self._cb_only_selected.setChecked(not self._app.selection_store.is_empty())
        self.refresh_from_app()
        self._wire_table_updates()
        self._sync_footer_chrome()
        self._sync_options_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        """Update the host app after dock/undock."""
        self.parent_app = parent_app
        self._app = parent_app
        self._refresh_row_table()

    def embedded_minimum_width(self) -> int:
        return max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), self.floating_content_minimum_width())

    def floating_content_minimum_width(self) -> int:
        """Width needed for footer + nav chrome without clipping."""
        return floating_browser_minimum_width(self, floor=self.embedded_minimum_width())

    def create_floating_dialog(self, parent_app) -> "SelectionBrowserDialog":
        """Re-open this browser in a floating window after undocking from the main table."""
        self.show()
        return SelectionBrowserDialog(parent_app, panel=self)

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, SelectionBrowserDialog):
            discard_host_dialog_after_dock(dlg, self.parent_app, "_selection_browser_dialog")

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_browser(self) -> None:
        request_close_plot_widget(
            self,
            title="Close Browser",
            message="Close this browser?",
        )

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return False

    def _apply_header_caption_font(self) -> None:
        """Use the compound-table header font so the caption matches header chrome."""
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
        floating = isinstance(self.window(), SelectionBrowserDialog)
        docked = self._is_docked_in_main_window()
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
        """Show or hide the current-row table from Browser Settings."""
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

    def _preview_mode_key(self) -> str:
        data = self._preview_mode_combo.currentData()
        if data in {
            BROWSER_PREVIEW_MODE_RDKIT_2D,
            BROWSER_PREVIEW_MODE_3DMOL_2D,
            BROWSER_PREVIEW_MODE_3DMOL_3D,
        }:
            return str(data)
        return DEFAULT_BROWSER_PREVIEW_MODE

    def _uses_3dmol_preview(self) -> bool:
        return self._preview_mode_key() in {
            BROWSER_PREVIEW_MODE_3DMOL_2D,
            BROWSER_PREVIEW_MODE_3DMOL_3D,
        }

    def set_preview_mode(self, mode: str) -> None:
        """Select a structure-view mode by catalog key."""
        key = str(mode or "").strip()
        if key not in {k for k, _ in BROWSER_PREVIEW_MODE_LABELS}:
            return
        if self._preview_mode_combo.currentData() == key:
            return
        _set_combo_current_data(self._preview_mode_combo, key)

    def apply_open_request(
        self,
        *,
        focus_oid: int | None = None,
        preview_mode: str | None = None,
    ) -> None:
        """Apply a Data → Browser / context-menu open: optional view mode and row focus."""
        if preview_mode:
            self.set_preview_mode(preview_mode)
        if focus_oid is not None:
            self.refresh_from_app(preserve_position=False)
            self.focus_oid(int(focus_oid))
            return
        self.refresh_from_app(preserve_position=True)
        self._show_first_selected_entry()

    def _show_first_selected_entry(self) -> None:
        """Show the first selected entry and scroll the compound table to it."""
        app = self._app
        if app is None or app.selection_store.is_empty():
            return
        selected = [r for r in app._selected_logical_rows() if self._row_navigable(r)]
        if not selected:
            return
        target = selected[0]
        if target in self._rows:
            self._idx = self._rows.index(target)
            self._sync_caption(target)
            self._update_preview(target)
        reveal = getattr(app, "reveal_first_selected_row", None)
        if callable(reveal):
            reveal(focus=False)

    def focus_oid(self, oid: int) -> None:
        """Walk to the table row for *oid*, expanding scope off “Browse Selected” if needed."""
        app = self._app
        if app is None:
            return
        target: int | None = None
        try:
            n = int(app._table_model.rowCount())
        except Exception:
            return
        want = int(oid)
        for r in range(n):
            try:
                if int(app._table_model.row_oid(r)) == want:
                    target = r
                    break
            except Exception:
                continue
        if target is None:
            return
        if target not in self._rows and self._cb_only_selected.isChecked():
            self._cb_only_selected.blockSignals(True)
            self._cb_only_selected.setChecked(False)
            self._cb_only_selected.blockSignals(False)
            self.refresh_from_app()
        if target not in self._rows:
            return
        self._idx = self._rows.index(target)
        self._focus_row(target)

    def _on_preview_mode_changed(self, _index: int = 0) -> None:
        self._preview_mode = self._preview_mode_key()
        self._sync_preview_mode()
        row = self._current_row()
        if row is not None:
            self._update_preview(row)
        elif self._uses_3dmol_preview() and self._view_3d is not None:
            self._view_3d.clear()

    def _ensure_3dmol_view(self, *, flat: bool) -> None:
        view = getattr(self, "_view_3d", None)
        if view is not None and bool(getattr(view, "_flat", False)) == bool(flat):
            return
        if view is not None:
            self._preview_ly.removeWidget(view)
            view.setParent(None)
            view.deleteLater()
            self._view_3d = None
        try:
            from ..mol_viewer_3d import Molecule3DEmbedView
        except Exception:
            return
        view = Molecule3DEmbedView(self._preview_host, flat=bool(flat))
        view.setMinimumSize(0, 0)
        view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._preview_ly.addWidget(view, 1)
        self._view_3d = view

    def _sync_preview_mode(self) -> None:
        mode = self._preview_mode_key()
        three_dmol = mode in {BROWSER_PREVIEW_MODE_3DMOL_2D, BROWSER_PREVIEW_MODE_3DMOL_3D}
        style_browser_preview_host(self._preview_host, canvas=mode != BROWSER_PREVIEW_MODE_3DMOL_3D)
        if three_dmol:
            self._ensure_3dmol_view(flat=mode == BROWSER_PREVIEW_MODE_3DMOL_2D)
            self._struct_label.hide()
            view = getattr(self, "_view_3d", None)
            if view is not None:
                view.show()
                view.schedule_refit()
            else:
                self._struct_label.show()
                self._struct_label.clear()
                self._struct_label.setPixmap(QPixmap())
                self._struct_label.setText("(3Dmol viewer unavailable)")
        else:
            self._struct_label.show()
            view = getattr(self, "_view_3d", None)
            if view is not None:
                view.hide()

    def _open_browser_options(self) -> None:
        show_plot_options_dialog(getattr(self, "_opts_dialog", None))

    def _toggle_options_visible(self) -> None:
        """Compatibility helper: flip Hide Options and refresh chrome."""
        hide = bool(getattr(self, "_options_visible", True))
        cb = getattr(self, "_cb_hide_options", None)
        if cb is not None:
            cb.setChecked(hide)
        else:
            self._options_visible = not hide
            self._sync_options_chrome()

    def event(self, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        return super().event(event)

    def _wire_table_updates(self) -> None:
        """Keep Browser in sync when the table, filters, or selection change."""
        if getattr(self, "_table_updates_wired", False):
            return
        app = self._app
        model = getattr(app, "_table_model", None)
        if model is None:
            return

        def _schedule_refresh() -> None:
            self._auto_refresh_timer.start()

        def _on_data_changed(top_left, bottom_right, roles=()) -> None:
            structure_col = CompoundTableModel.STRUCTURE_COL
            if (
                top_left.isValid()
                and bottom_right.isValid()
                and top_left.column() == structure_col
                and bottom_right.column() == structure_col
            ):
                paint_roles = {
                    Qt.DecorationRole,
                    Qt.SizeHintRole,
                    Qt.DisplayRole,
                    Qt.ToolTipRole,
                }
                if not roles or set(roles) <= paint_roles:
                    return
            _schedule_refresh()

        model.dataChanged.connect(_on_data_changed)
        model.rowsInserted.connect(_schedule_refresh)
        model.rowsRemoved.connect(_schedule_refresh)
        model.modelReset.connect(_schedule_refresh)
        model.layoutChanged.connect(_schedule_refresh)
        model.headerDataChanged.connect(_schedule_refresh)
        proxy = getattr(app, "_filter_proxy_model", None)
        if proxy is not None:
            proxy.layoutChanged.connect(_schedule_refresh)
            proxy.modelReset.connect(_schedule_refresh)
        app.selection_store.changed.connect(self._on_selection_store_changed)
        self._table_updates_wired = True

    def _on_selection_store_changed(self, origin: object) -> None:
        """Rescope only when browsing the selection; otherwise just restate the toggle button."""
        if origin is self:
            return
        if self._cb_only_selected.isChecked():
            self._selection_refresh_timer.start()
        else:
            self._sync_select_button()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        if self._uses_3dmol_preview():
            view = getattr(self, "_view_3d", None)
            if view is not None:
                view.schedule_refit()
            return
        if self._rows and 0 <= self._idx < len(self._rows):
            self._update_preview(self._rows[self._idx])

    def refresh_from_app(
        self, *, preserve_position: bool = False, keep_previews: bool = False
    ) -> None:
        """Recompute row scope; optionally keep the current row (by OID) when the table changes.

        ``keep_previews`` skips dropping cached structure previews; pass it when only the
        selection changed, since the row data the previews depict is unchanged.
        """
        with perf_span("selection.browser_refresh"):
            self._refresh_from_app_now(
                preserve_position=preserve_position, keep_previews=keep_previews
            )

    def _refresh_from_app_now(self, *, preserve_position: bool, keep_previews: bool) -> None:
        app = self._app
        cur_oid: int | None = None
        if preserve_position:
            row = self._current_row()
            if row is not None:
                try:
                    cur_oid = int(app._table_model.row_oid(row))
                except Exception:
                    cur_oid = None
        self._refresh_row_table()
        self._rows = self._rows_for_scope(app)
        self._idx = 0
        if self._rows:
            if preserve_position and cur_oid is not None:
                for j, rr in enumerate(self._rows):
                    try:
                        if int(app._table_model.row_oid(rr)) == cur_oid:
                            self._idx = j
                            break
                    except Exception:
                        continue
            self._idx = self._first_navigable_index(self._idx, +1)
        if not keep_previews:
            self._preview_pix_cache.clear()
        self._update_ui(scroll_table=not preserve_position)

    def _rows_for_scope(self, app: Any) -> list[int]:
        visible = app._visible_source_row_indices()
        if self._cb_only_selected.isChecked():
            raw = list(app._selected_logical_rows())
            if visible is None:
                vis = raw
            else:
                vis_set = set(visible)
                vis = [r for r in raw if r in vis_set]
            return vis if vis else raw
        n = int(app._table_model.rowCount())
        if visible is None:
            return list(range(n))
        ordered = [r for r in range(n) if r in set(visible)]
        if ordered:
            return ordered
        return list(range(n))

    def _row_navigable(self, r: int) -> bool:
        if not (0 <= r < self._app._table_model.rowCount()):
            return False
        return self._app._is_source_row_visible(r)

    def _first_navigable_index(self, start: int, delta: int) -> int:
        n = len(self._rows)
        if n == 0:
            return 0
        i = start % n
        for _ in range(n):
            if self._row_navigable(self._rows[i]):
                return i
            i = (i + delta) % n
        return start % n

    def _last_navigable_index(self) -> int:
        n = len(self._rows)
        if n == 0:
            return 0
        for i in range(n - 1, -1, -1):
            if self._row_navigable(self._rows[i]):
                return i
        return self._first_navigable_index(0, +1)

    def _go_first(self) -> None:
        if not self._rows:
            return
        self._idx = self._first_navigable_index(0, +1)
        self._focus_row(self._rows[self._idx])

    def _go_last(self) -> None:
        if not self._rows:
            return
        self._idx = self._last_navigable_index()
        self._focus_row(self._rows[self._idx])

    def _step(self, delta: int) -> None:
        n = len(self._rows)
        if n == 0:
            return
        if n == 1:
            self._focus_row(self._rows[0])
            return
        nxt = (self._idx + delta) % n
        start = nxt
        for _ in range(n):
            r = self._rows[nxt]
            if self._row_navigable(r):
                self._idx = nxt
                self._focus_row(r)
                return
            nxt = (nxt + delta) % n
            if nxt == start:
                break
        self._idx = self._first_navigable_index(self._idx, delta)
        if self._rows:
            self._focus_row(self._rows[self._idx])

    def _view_index_for_source_row(
        self, logical_row: int, *, column: int = CompoundTableModel.STRUCTURE_COL
    ):
        app = self._app
        m = app._table_model
        if logical_row < 0 or logical_row >= m.rowCount():
            return None
        src_ix = m.index(logical_row, column)
        proxy = getattr(app, "_filter_proxy_model", None)
        view_model = app.table.model()
        if proxy is not None and view_model is proxy:
            view_ix = proxy.mapFromSource(src_ix)
            return view_ix if view_ix.isValid() else None
        return src_ix if src_ix.isValid() else None

    def _focus_row(self, logical_row: int) -> None:
        app = self._app
        tbl = app.table
        view_ix = self._view_index_for_source_row(logical_row)
        if view_ix is None:
            return
        sm = tbl.selectionModel()
        if sm is not None:
            sm.setCurrentIndex(view_ix, QItemSelectionModel.Current)
        tbl.scrollTo(view_ix, QAbstractItemView.PositionAtCenter)
        self._sync_caption(logical_row)
        self._update_preview(logical_row)

    def _on_index_edited(self, value: int) -> None:
        if self._index_syncing:
            return
        n = len(self._rows)
        if n <= 0:
            return
        target = max(0, min(int(value) - 1, n - 1))
        resolved = self._first_navigable_index(target, +1)
        if resolved == self._idx:
            self._sync_index_field(n)
            return
        self._idx = resolved
        self._focus_row(self._rows[self._idx])

    def _sync_index_field(self, count: int) -> None:
        self._index_scope_label.setText("Selected" if self._cb_only_selected.isChecked() else "Row")
        spin = self._index_edit
        self._index_syncing = True
        spin.blockSignals(True)
        try:
            if count <= 0:
                spin.setRange(1, 1)
                spin.setValue(1)
                spin.setEnabled(False)
                self._index_count_label.setText("/ 0")
            else:
                shown = max(1, min(self._idx + 1, count))
                spin.setEnabled(True)
                spin.setRange(1, count)
                spin.setValue(shown)
                self._index_count_label.setText(f"/ {count}")
        finally:
            spin.blockSignals(False)
            self._index_syncing = False

    def _sync_caption(self, _logical_row: int) -> None:
        self._meta.clear()
        self._meta.setVisible(False)
        self._sync_index_field(len(self._rows))
        self._update_property_values()

    def _visible_data_columns(self) -> list[tuple[int, str]]:
        """Visible non-structure table columns in visual order."""
        app = self._app
        headers = list(getattr(app, "headers", []) or [])
        table = getattr(app, "table", None)
        vis_fn = getattr(app, "_visual_logical_columns", None)
        logical = vis_fn() if callable(vis_fn) else list(range(len(headers)))
        out: list[tuple[int, str]] = []
        for i in logical:
            if i < 0 or i >= len(headers):
                continue
            name = str(headers[i])
            if name in ("ID_HIDDEN", "Structure"):
                continue
            if table is not None:
                try:
                    if table.isColumnHidden(i):
                        continue
                except RuntimeError:
                    pass
            out.append((i, name))
        return out

    def _refresh_row_table(self) -> None:
        """Rebuild the one-row table headers from the main compound table."""
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        cols = self._visible_data_columns()
        names = [name for _i, name in cols]
        table.blockSignals(True)
        table.setColumnCount(len(names))
        table.setHorizontalHeaderLabels(names)
        table.blockSignals(False)
        self._fill_row_table()

    def _row_table_item_for_cell(self, logical_row: int, col: int) -> QTableWidgetItem:
        app = self._app
        model = getattr(app, "_table_model", None)
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        if model is None:
            return item
        index = model.index(logical_row, col)
        pix = model.data(index, Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            scaled = pix.scaled(
                _ROW_TABLE_PIXMAP_MAX,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            item.setIcon(QIcon(scaled))
            item.setText("")
        else:
            cell_fn = getattr(app, "_table_cell_text", None)
            text = ""
            if callable(cell_fn):
                text = (cell_fn(logical_row, col) or "").strip()
            if not text:
                text = (model.cell_text(logical_row, col) or "").strip()
            item.setText(text)
            if text:
                item.setToolTip(text)
        bg = model.data(index, Qt.BackgroundRole)
        if bg is not None:
            item.setBackground(bg if isinstance(bg, QBrush) else QBrush(bg))
        return item

    def _fit_row_table_height(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        hdr_h = int(table.horizontalHeader().sizeHint().height())
        frame = 2 * int(table.frameWidth())
        style = table.style()
        extent = int(style.pixelMetric(QStyle.PM_ScrollBarExtent, None, table))
        bar = table.horizontalScrollBar()
        hinted = int(bar.sizeHint().height()) if bar is not None else 0
        scroll = max(extent, hinted, 16)
        table.setFixedHeight(hdr_h + _ROW_TABLE_ROW_HEIGHT + frame + scroll + 4)

    def _fill_row_table(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        cols = self._visible_data_columns()
        row = self._current_row()
        table.blockSignals(True)
        table.setRowCount(0 if row is None else 1)
        if row is not None:
            for i, (col, _name) in enumerate(cols):
                table.setItem(0, i, self._row_table_item_for_cell(row, col))
            table.setRowHeight(0, _ROW_TABLE_ROW_HEIGHT)
        table.blockSignals(False)
        self._fit_row_table_height()

    def _current_row(self) -> int | None:
        if not self._rows:
            return None
        if not (0 <= self._idx < len(self._rows)):
            return None
        return self._rows[self._idx]

    def _is_row_selected(self, logical_row: int) -> bool:
        try:
            oid = int(self._app._table_model.row_oid(logical_row))
        except (IndexError, ValueError, TypeError):
            return False
        return self._app.selection_store.contains(oid)

    def _toggle_current_row_selected(self) -> None:
        r = self._current_row()
        if r is None:
            return
        app = self._app
        try:
            oid = int(app._table_model.row_oid(r))
        except (IndexError, ValueError, TypeError):
            return
        app.select_table_oids(app.selection_store.oids ^ {oid}, origin=self, reveal=False)

        if self._cb_only_selected.isChecked():
            self.refresh_from_app(keep_previews=True)
            if self._rows:
                for j, rr in enumerate(self._rows):
                    try:
                        if int(app._table_model.row_oid(rr)) == oid:
                            self._idx = j
                            break
                    except Exception:
                        continue
                self._update_ui()
        else:
            self._sync_select_button()

    def _update_property_values(self) -> None:
        self._fill_row_table()
        self._sync_select_button()

    def _sync_select_button(self) -> None:
        r = self._current_row()
        if r is None:
            self._btn_toggle_select.setEnabled(False)
            self._btn_toggle_select.setChecked(False)
            self._btn_toggle_select.setToolTip("Select or deselect this row in the table")
            return
        self._btn_toggle_select.setEnabled(True)
        selected = self._is_row_selected(r)
        self._btn_toggle_select.setChecked(selected)
        self._btn_toggle_select.setToolTip(
            "Deselect this row in the table" if selected else "Select this row in the table"
        )

    def _structure_pixmap(self, logical_row: int):
        m = self._app._table_model
        ix = m.index(logical_row, CompoundTableModel.STRUCTURE_COL)
        return m.data(ix, Qt.DecorationRole)

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        host = getattr(self, "_preview_host", None) or self._struct_label
        lw = int(host.width())
        lh = int(host.height())
        # Use the label's current box; only fall back before the first layout pass.
        if lw < 2:
            lw = max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)
        if lh < 2:
            lh = max(260, BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2)
        return max(1, int(lw * dpr)), max(1, int(lh * dpr)), dpr

    def _render_preview_pixmap(self, logical_row: int, pw: int, ph: int) -> QPixmap | None:
        try:
            from rdkit.Chem.Draw import rdMolDraw2D
        except Exception:
            return None
        app = self._app
        try:
            oid = int(app._table_model.row_oid(logical_row))
        except Exception:
            return None
        from ...chem.depiction_coords import depiction_revision, mol_for_app_depiction

        cache_key = (oid, pw, ph, depiction_revision(app))
        cached = self._preview_pix_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            return cached
        mol = mol_for_app_depiction(app, getattr(app, "mols", {}).get(oid), oid)
        if mol is None:
            return None
        try:
            d = rdMolDraw2D.MolDraw2DCairo(pw, ph)
            opts = d.drawOptions()
            # Keep molecule canvas white to match the preview host background.
            opts.setBackgroundColour((1.0, 1.0, 1.0, 1.0))
            rdMolDraw2D.PrepareAndDrawMolecule(d, mol)
            d.FinishDrawing()
            img = QImage.fromData(d.GetDrawingText())
            pm = QPixmap.fromImage(img)
            if not pm.isNull():
                self._preview_pix_cache[cache_key] = pm
                return pm
        except Exception:
            return None
        return None

    def _update_preview_3dmol(self, logical_row: int) -> None:
        flat = self._preview_mode_key() == BROWSER_PREVIEW_MODE_3DMOL_2D
        self._ensure_3dmol_view(flat=flat)
        view = getattr(self, "_view_3d", None)
        if view is None:
            self._struct_label.show()
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("(3Dmol viewer unavailable)")
            return
        app = self._app
        try:
            oid = int(app._table_model.row_oid(logical_row))
        except Exception:
            view.clear()
            return
        mol = getattr(app, "mols", {}).get(oid)
        if flat and mol is not None:
            from ...chem.depiction_coords import mol_for_app_depiction

            mol = mol_for_app_depiction(app, mol, oid)
        view.set_molecule(mol, rebuild_3d=False)

    def _update_preview(self, logical_row: int) -> None:
        if self._uses_3dmol_preview():
            self._sync_preview_mode()
            self._update_preview_3dmol(logical_row)
            return
        self._sync_preview_mode()
        pw, ph, dpr = self._preview_pixel_size()
        pm = self._render_preview_pixmap(logical_row, pw, ph)
        if pm is None or pm.isNull():
            table_pm = self._structure_pixmap(logical_row)
            if isinstance(table_pm, QPixmap) and not table_pm.isNull():
                if table_pm.width() >= pw * 0.9 and table_pm.height() >= ph * 0.9:
                    pm = table_pm
        if isinstance(pm, QPixmap) and not pm.isNull():
            if pm.width() != pw or pm.height() != ph:
                pm = pm.scaled(pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._struct_label.setPixmap(pm)
            self._struct_label.setText("")
        else:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("(no structure available)")

    def _update_ui(self, *, scroll_table: bool = True) -> None:
        n = len(self._rows)
        single = n <= 1
        has_rows = n > 0
        self._btn_first.setEnabled(has_rows)
        self._btn_last.setEnabled(has_rows)
        self._btn_back.setEnabled(not single and has_rows)
        self._btn_fwd.setEnabled(not single and has_rows)
        if n == 0:
            self._meta.setVisible(True)
            if self._cb_only_selected.isChecked():
                self._meta.setText(
                    "No rows selected — uncheck “Browse Selected” or select rows in the table."
                )
            else:
                self._meta.setText("Table is empty.")
            self._sync_index_field(0)
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("")
            view = getattr(self, "_view_3d", None)
            if view is not None:
                view.clear()
            self._fill_row_table()
            self._sync_select_button()
            return
        self._idx = max(0, min(self._idx, n - 1))
        self._idx = self._first_navigable_index(self._idx, +1)
        r = self._rows[self._idx]
        if scroll_table:
            self._focus_row(r)
        else:
            self._sync_caption(r)
            self._update_preview(r)


class SelectionBrowserDialog(BrowserHostDialog):
    """Floating window hosting a :class:`SelectionBrowserWidget`."""

    default_title = "Browser"
    panel_cls = SelectionBrowserWidget
    fit_chrome = True
    sync_options_chrome = True

    def refresh_from_app(self, *, preserve_position: bool = False) -> None:
        self._panel.refresh_from_app(preserve_position=preserve_position)
