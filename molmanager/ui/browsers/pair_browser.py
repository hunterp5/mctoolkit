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

"""Shared floating shell for side-by-side pair browsers (MMP, SALI)."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QGroupBox,
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
from ..dockable_plot import add_centered_browser_nav, style_browser_nav_buttons
from ..qt_widget_utils import make_window_resizable
from .chrome import (
    BrowserIndexSpinBox,
    apply_browser_body_layout,
    install_browser_nav_shortcuts,
    make_pair_mol_panel,
    style_browser_data_table,
    style_browser_emphasis_label,
    style_browser_group_box,
)

_PAIR_TABLE_ROW_HEIGHT = 28

# Atoms that differ between the two molecules (outside the MCS).
_CHANGED_ATOM_RGB = (0.95, 0.55, 0.15)


class PairBrowserDialog(QDialog):
    """Two-molecule pair browser: depictions, a summary, the pair's table rows, and nav."""

    window_title = "Pairs"
    select_status = "pair"

    def __init__(self, parent: Any, *, activity_column: str):
        super().__init__(parent)
        self._app = parent
        self._activity_column = activity_column
        self._idx = getattr(self, "_idx", 0)
        self._preview_cache: dict[tuple, QPixmap] = getattr(self, "_preview_cache", {})
        self._highlight_cache: dict[tuple, tuple[list[int], list[int]]] = getattr(
            self, "_highlight_cache", {}
        )
        self._prefer_keys: tuple[int, int] | None = getattr(self, "_prefer_keys", None)
        self._pair_index_syncing = False

        self.setWindowTitle(self.window_title)
        self.resize(920, 620)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignCenter)
        root.addWidget(self._meta)

        self._populate_header(root)

        pair_row = QHBoxLayout()
        pair_row.setSpacing(8)
        self._left_panel = make_pair_mol_panel("Molecule A")
        self._right_panel = make_pair_mol_panel("Molecule B")
        pair_row.addWidget(self._left_panel["box"], 1)
        pair_row.addWidget(self._right_panel["box"], 1)
        root.addLayout(pair_row, 1)

        self._add_comparison_section(root)

        self._prepare_nav_extras()
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First pair (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous pair (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next pair (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last pair (End)")
        self._btn_select = QPushButton()
        self._btn_select.setToolTip("Select both molecules of this pair in the main table")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
            self._btn_select,
        )
        self._cb_selected_only = QCheckBox("Selected Only")
        self._cb_selected_only.setToolTip(
            "When checked, browse only pairs that involve at least one molecule "
            "from the current table selection."
        )
        add_centered_browser_nav(
            nav,
            [
                self._btn_first,
                self._btn_back,
                self._btn_fwd,
                self._btn_last,
                self._btn_select,
            ],
            leading=self._nav_leading_widgets(),
            trailing=self._nav_trailing_widgets(),
        )
        self._nav_layout = nav
        root.addLayout(nav)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_select.clicked.connect(self._select_current_pair)
        self._cb_selected_only.toggled.connect(self._on_selected_only_toggled)
        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_previews)

        make_window_resizable(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self._refresh_property_columns()
        self._update_ui()

    def _populate_header(self, root: QVBoxLayout) -> None:
        """Optional widgets between the caption and the pair cards."""

    def _shows_pair_summary(self) -> bool:
        """False omits the summary group under the depictions."""
        return True

    def _populate_metrics(self, layout: QVBoxLayout) -> None:
        """Centered pair summary. Subclasses may add widgets above the label."""
        self._metrics_label = QLabel(self._metrics_box)
        self._metrics_label.setAlignment(Qt.AlignCenter)
        self._metrics_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._metrics_label.setWordWrap(True)
        style_browser_emphasis_label(self._metrics_label)
        layout.addWidget(self._metrics_label)

    def _add_comparison_section(self, root: QVBoxLayout) -> None:
        """Summary under the depictions, then a two-row table of the current pair."""
        if self._shows_pair_summary():
            self._metrics_box = QGroupBox()
            style_browser_group_box(self._metrics_box)
            metrics_layout = QVBoxLayout(self._metrics_box)
            metrics_layout.setContentsMargins(8, 8, 8, 8)
            self._populate_metrics(metrics_layout)
            root.addWidget(self._metrics_box)

        self._row_table = QTableWidget(0, 0, self)
        self._row_table.setObjectName("BrowserRowTable")
        self._row_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._row_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._row_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._row_table.setFocusPolicy(Qt.NoFocus)
        self._row_table.verticalHeader().setVisible(True)
        self._row_table.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self._row_table.verticalHeader().setDefaultSectionSize(_PAIR_TABLE_ROW_HEIGHT)
        self._row_table.horizontalHeader().setHighlightSections(False)
        self._row_table.horizontalHeader().setStretchLastSection(True)
        self._row_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._row_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._row_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._row_table.setWordWrap(False)
        self._row_table.setShowGrid(True)
        self._row_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        style_browser_data_table(self._row_table)
        bar = self._row_table.horizontalScrollBar()
        if bar is not None:
            bar.rangeChanged.connect(lambda *_a: self._fit_pair_table_height())
        self._fit_pair_table_height()
        root.addWidget(self._row_table)
        self._place_side_names_with_activity()

    def _place_side_names_with_activity(self) -> None:
        """Put Molecule A / B on the activity line under each depiction."""
        for panel, side in (
            (self._left_panel, "Molecule A"),
            (self._right_panel, "Molecule B"),
        ):
            box = panel["box"]
            activity: QLabel = panel["activity"]
            layout = box.layout()
            layout.removeWidget(activity)
            name = QLabel(side, box)
            name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            name.setTextInteractionFlags(Qt.TextSelectableByMouse)
            style_browser_emphasis_label(name)
            activity.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            host = QWidget(box)
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            row.addStretch(1)
            row.addWidget(name)
            row.addWidget(activity)
            row.addStretch(1)
            layout.addWidget(host)
            panel["name"] = name
            panel["caption_host"] = host
            box.setTitle("")
            style_browser_group_box(box)

    def _prepare_nav_extras(self) -> None:
        """Pair number field on the leading side of the nav row."""
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 10, 0)
        row.setSpacing(4)
        pair_label = QLabel("Pair")
        pair_label.setAlignment(Qt.AlignVCenter)
        self._pair_index = BrowserIndexSpinBox(host)
        self._pair_index.setToolTip("Type a pair number and press Enter to jump to that pair.")
        n = self._item_count()
        if n > 0:
            self._pair_index.setRange(1, n)
            self._pair_index.setValue(min(self._idx + 1, n))
        self._pair_count_label = QLabel("/ 0" if n <= 0 else f"/ {n}")
        self._pair_count_label.setAlignment(Qt.AlignVCenter)
        row.addWidget(pair_label)
        row.addWidget(self._pair_index)
        row.addWidget(self._pair_count_label)
        self._pair_index_host = host
        self._pair_index.valueChanged.connect(self._on_pair_index_changed)

    def _nav_leading_widgets(self) -> list[QWidget]:
        return [self._pair_index_host]

    def _nav_trailing_widgets(self) -> list[QWidget]:
        return [self._cb_selected_only]

    def _on_pair_index_changed(self, value: int) -> None:
        if self._pair_index_syncing:
            return
        n = self._item_count()
        if n <= 0:
            return
        target = max(0, min(int(value) - 1, n - 1))
        if target == self._idx:
            return
        self._idx = target
        self._update_ui()

    def _sync_pair_index(self, count: int) -> None:
        spin = self._pair_index
        self._pair_index_syncing = True
        spin.blockSignals(True)
        try:
            if count <= 0:
                spin.setRange(1, 1)
                spin.setValue(1)
                spin.setEnabled(False)
                self._pair_count_label.setText("/ 0")
            else:
                shown = max(1, min(self._idx + 1, count))
                spin.setEnabled(True)
                spin.setRange(1, count)
                spin.setValue(shown)
                self._pair_count_label.setText(f"/ {count}")
        finally:
            spin.blockSignals(False)
            self._pair_index_syncing = False

    def _item_count(self) -> int:
        raise NotImplementedError

    def _current_pair_oids(self) -> tuple[int, int] | None:
        raise NotImplementedError

    def _on_selected_only_toggled(self, _checked: bool) -> None:
        raise NotImplementedError

    def _update_ui(self) -> None:
        raise NotImplementedError

    def _refresh_previews(self) -> None:
        raise NotImplementedError

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._resize_timer.start()

    def _selected_oids(self) -> set[int]:
        app = self._app
        if app is None:
            return set()
        try:
            return {int(o) for o in app._selected_oids_set()}
        except Exception:
            return set()

    def _go_first(self) -> None:
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._idx = max(0, self._item_count() - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        n = self._item_count()
        if n <= 0:
            return
        self._idx = (self._idx + int(delta)) % n
        self._update_ui()

    def _select_current_pair(self) -> None:
        oids = self._current_pair_oids()
        app = self._app
        if oids is None or app is None:
            return
        try:
            app.select_table_oids([oids[0], oids[1]], extra_status=self.select_status)
        except Exception:
            pass

    def _sync_nav_enabled(self, *, count: int, extra: list[QWidget] | None = None) -> None:
        has = count > 0
        self._btn_first.setEnabled(has)
        self._btn_last.setEnabled(has)
        self._btn_back.setEnabled(count > 1)
        self._btn_fwd.setEnabled(count > 1)
        self._btn_select.setEnabled(has)
        for widget in extra or []:
            widget.setEnabled(has)

    def _clear_pair_panels(self) -> None:
        for panel in (self._left_panel, self._right_panel):
            panel["struct"].clear()
            panel["struct"].setPixmap(QPixmap())
            panel["activity"].setText("—")

    def _visible_data_columns(self) -> list[tuple[int, str]]:
        """Visible non-structure table columns in visual order."""
        app = self._app
        if app is None:
            return []
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

    def _pair_table_item(self, oid: int, col: int, header: str) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        text = self._cell_text_for_oid(int(oid), header)
        item.setText(text)
        if text:
            item.setToolTip(text)
        app = self._app
        model = getattr(app, "_table_model", None) if app is not None else None
        if model is None:
            return item
        try:
            row = app.logical_row_for_oid(int(oid))
        except Exception:
            return item
        if row is None or int(row) < 0:
            return item
        try:
            index = model.index(int(row), int(col))
            bg = model.data(index, Qt.BackgroundRole)
        except Exception:
            return item
        if bg is not None:
            item.setBackground(bg if isinstance(bg, QBrush) else QBrush(bg))
        return item

    def _fit_pair_table_height(self) -> None:
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
        table.setFixedHeight(hdr_h + 2 * _PAIR_TABLE_ROW_HEIGHT + frame + scroll + 4)

    def _fill_pair_table(self) -> None:
        table = getattr(self, "_row_table", None)
        if table is None:
            return
        cols = self._visible_data_columns()
        names = [name for _col, name in cols]
        current = []
        for i in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(i)
            current.append("" if header_item is None else header_item.text())
        table.blockSignals(True)
        if current != names:
            table.setColumnCount(len(names))
            if names:
                table.setHorizontalHeaderLabels(names)
        oids = self._current_pair_oids()
        if oids is None:
            table.setRowCount(0)
        else:
            table.setRowCount(2)
            table.setVerticalHeaderLabels(["A", "B"])
            for row, oid in enumerate(oids):
                for i, (col, name) in enumerate(cols):
                    table.setItem(row, i, self._pair_table_item(int(oid), col, name))
                table.setRowHeight(row, _PAIR_TABLE_ROW_HEIGHT)
        table.blockSignals(False)
        self._fit_pair_table_height()

    def _refresh_property_columns(self) -> None:
        self._fill_pair_table()

    def _cell_text_for_oid(self, oid: int, header: str) -> str:
        app = self._app
        if app is None or not header:
            return ""
        try:
            row = app.logical_row_for_oid(int(oid))
        except Exception:
            return ""
        if row is None or row < 0:
            return ""
        try:
            col = int(app.headers.index(header))
        except Exception:
            return ""
        try:
            text = (app._table_cell_text(row, col) or "").strip()
            if not text:
                text = (app._table_model.backing_value_for_row_header(row, header) or "").strip()
            return text
        except Exception:
            return ""

    def _update_property_values(self) -> None:
        self._fill_pair_table()

    def _preview_pixel_size(self, label: QLabel) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = max(label.width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)
        lh = max(label.height(), BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2)
        return int(lw * dpr), int(lh * dpr), dpr

    def _variable_highlights(
        self,
        key: tuple[int, int],
        mol_a: Any,
        mol_b: Any,
    ) -> tuple[list[int], list[int]]:
        """Atoms outside the shared MCS, cached per molecule pair."""
        cached = self._highlight_cache.get(key)
        if cached is not None:
            return cached
        if mol_a is None or mol_b is None:
            return [], []
        from ...analysis.mmp_depict import highlight_atoms_for_pair

        found = highlight_atoms_for_pair(mol_a, mol_b)
        self._highlight_cache[key] = found
        return found

    def _render_highlighted(
        self,
        mol: Any,
        pw: int,
        ph: int,
        highlight_atoms: list[int],
    ) -> QPixmap | None:
        """Draw *mol* with the atoms that differ from its partner marked."""
        try:
            from ...chem.depiction_scene import atom_set_highlight
            from ...table.structure_image import molecule_pixmap

            highlight = atom_set_highlight(mol, highlight_atoms, _CHANGED_ATOM_RGB)
            return molecule_pixmap(mol, pw, ph, highlight=highlight)
        except Exception:
            return None

    def _show_molecule(
        self,
        panel: dict[str, Any],
        caption: str,
        mol: Any,
        highlight_atoms: list[int],
        cache_token: tuple,
    ) -> None:
        """Caption and depiction for one side, with variable atoms highlighted."""
        panel["activity"].setText(caption)
        label: QLabel = panel["struct"]
        pw, ph, dpr = self._preview_pixel_size(label)
        if mol is None:
            label.clear()
            label.setPixmap(QPixmap())
            label.setText("(no structure)")
            return

        from ...chem.depiction_coords import depiction_revision

        cache_key = (cache_token, pw, ph, depiction_revision(self._app))
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            pm = cached
        else:
            pm = self._render_highlighted(mol, pw, ph, highlight_atoms)
            if pm is not None and not pm.isNull():
                self._preview_cache[cache_key] = pm
        if pm is None or pm.isNull():
            label.clear()
            label.setPixmap(QPixmap())
            label.setText("(render failed)")
            return
        if pm.width() != pw or pm.height() != ph:
            pm = pm.scaled(pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        label.setPixmap(pm)
        label.setText("")
