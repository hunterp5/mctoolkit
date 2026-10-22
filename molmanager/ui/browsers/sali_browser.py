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

"""Browse SALI pairs side-by-side with a data table for the current pair."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...analysis.sali_analysis import SaliPoint, as_sali_activity
from ...table.structure_image import molecule_pixmap
from .chrome import (
    BrowserIndexSpinBox,
    style_browser_data_table,
    style_browser_emphasis_label,
    style_browser_group_box,
)
from .pair_browser import PairBrowserDialog

_PAIR_TABLE_ROW_HEIGHT = 28


class SaliBrowserDialog(PairBrowserDialog):
    """Step through SALI pairs: two molecules, activities, similarity, and SALI."""

    window_title = "SALI Pairs"
    select_status = "SALI pair"

    def __init__(
        self,
        parent: Any,
        points: list[SaliPoint],
        *,
        activity_column: str,
        fp_choice: str = "",
        metric: str = "Tanimoto",
        start_index: int = 0,
        off_target_column: str = "",
        treat_logarithmically: bool = False,
    ):
        self._all_points = list(points)
        self._points = list(points)
        self._fp_choice = fp_choice or ""
        self._metric = metric or "Tanimoto"
        self._off_target_column = off_target_column or ""
        self._treat_logarithmically = bool(treat_logarithmically)
        self._idx = max(0, int(start_index))
        if self._all_points and 0 <= self._idx < len(self._all_points):
            p0 = self._all_points[self._idx]
            self._prefer_keys = (int(p0.oid_a), int(p0.oid_b))
        self._pair_index_syncing = False
        super().__init__(parent, activity_column=activity_column)

    def _add_comparison_section(self, root: QVBoxLayout) -> None:
        """Pair metrics, then a two-row table of the current pair."""
        self._metrics_box = QGroupBox()
        style_browser_group_box(self._metrics_box)
        metrics_layout = QVBoxLayout(self._metrics_box)
        metrics_layout.setContentsMargins(8, 8, 8, 8)
        self._metrics_label = QLabel(self._metrics_box)
        self._metrics_label.setAlignment(Qt.AlignCenter)
        self._metrics_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._metrics_label.setWordWrap(True)
        style_browser_emphasis_label(self._metrics_label)
        metrics_layout.addWidget(self._metrics_label)
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

    def _prepare_nav_extras(self) -> None:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 10, 0)
        row.setSpacing(4)
        pair_label = QLabel("Pair")
        pair_label.setAlignment(Qt.AlignVCenter)
        self._pair_index = BrowserIndexSpinBox(host)
        self._pair_index.setToolTip("Type a pair number and press Enter to jump to that pair.")
        n = len(self._points)
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
        return len(self._points)

    def _current_pair_oids(self) -> tuple[int, int] | None:
        point = self._current_point()
        if point is None:
            return None
        return (int(point.oid_a), int(point.oid_b))

    def set_points(
        self,
        points: list[SaliPoint],
        *,
        activity_column: str | None = None,
        fp_choice: str | None = None,
        metric: str | None = None,
        start_index: int | None = None,
        off_target_column: str | None = None,
        treat_logarithmically: bool | None = None,
    ) -> None:
        """Replace the pair list and refresh the view."""
        self._all_points = list(points or [])
        if activity_column is not None:
            self._activity_column = activity_column
        if fp_choice is not None:
            self._fp_choice = fp_choice
        if metric is not None:
            self._metric = metric
        if off_target_column is not None:
            self._off_target_column = off_target_column
        if treat_logarithmically is not None:
            self._treat_logarithmically = bool(treat_logarithmically)
        prefer: tuple[int, int] | None = None
        if start_index is not None and self._all_points:
            si = max(0, min(int(start_index), len(self._all_points) - 1))
            p0 = self._all_points[si]
            prefer = (int(p0.oid_a), int(p0.oid_b))
        elif self._all_points:
            prefer = (int(self._all_points[0].oid_a), int(self._all_points[0].oid_b))
        self._prefer_keys = prefer
        self._preview_cache.clear()
        self._refresh_property_columns()
        self._rebuild_filtered_points(update_ui=True)

    def _on_selected_only_toggled(self, _checked: bool) -> None:
        cur = self._current_point()
        if cur is not None:
            self._prefer_keys = (int(cur.oid_a), int(cur.oid_b))
        self._rebuild_filtered_points(update_ui=True)

    def _rebuild_filtered_points(self, *, update_ui: bool) -> None:
        source = list(self._all_points)
        if self._cb_selected_only.isChecked():
            selected = self._selected_oids()
            if selected:
                source = [p for p in source if int(p.oid_a) in selected or int(p.oid_b) in selected]
            else:
                source = []
        self._points = source
        prefer = self._prefer_keys
        self._idx = 0
        if prefer is not None:
            for i, p in enumerate(self._points):
                if (int(p.oid_a), int(p.oid_b)) == prefer:
                    self._idx = i
                    break
        if update_ui:
            self._update_ui()

    def _current_point(self) -> SaliPoint | None:
        if not self._points or not (0 <= self._idx < len(self._points)):
            return None
        return self._points[self._idx]

    def _activity_for_oid(self, oid: int) -> float | None:
        header = self._activity_column
        if not header:
            return None
        text = self._cell_text_for_oid(int(oid), header)
        if not text:
            return None
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None

    def _refresh_previews(self) -> None:
        point = self._current_point()
        if point is None:
            return
        act_a = self._activity_for_oid(point.oid_a)
        act_b = self._activity_for_oid(point.oid_b)
        self._update_molecule_panel(self._left_panel, point.oid_a, act_a)
        self._update_molecule_panel(self._right_panel, point.oid_b, act_b)

    def _update_ui(self) -> None:
        n = len(self._points)
        self._sync_nav_enabled(count=n)
        if n <= 0:
            self._meta.setVisible(True)
            if self._cb_selected_only.isChecked():
                self._meta.setText("No SALI pairs involve the current table selection.")
            else:
                self._meta.setText("No SALI pairs to browse.")
            self._metrics_label.setText("")
            self._sync_pair_index(0)
            self._clear_pair_panels()
            self._update_property_values()
            return

        self._idx = max(0, min(self._idx, n - 1))
        point = self._points[self._idx]
        self._meta.clear()
        self._meta.setVisible(False)
        self._sync_pair_index(n)
        self._metrics_label.setText(self._metrics_text(point))
        self._left_panel["box"].setTitle(f"Molecule A  (ID {point.oid_a})")
        self._right_panel["box"].setTitle(f"Molecule B  (ID {point.oid_b})")
        self._refresh_previews()
        self._update_property_values()

    def _refresh_property_columns(self) -> None:
        self._fill_pair_table()

    def _update_property_values(self) -> None:
        self._fill_pair_table()

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

    def _mol_for_oid(self, oid: int) -> Chem.Mol | None:
        app = self._app
        if app is None:
            return None
        from ...chem.depiction_coords import mol_for_app_depiction

        return mol_for_app_depiction(app, getattr(app, "mols", {}).get(int(oid)), int(oid))

    def _signed_text(self, value: float) -> str:
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.4g}"

    def _scaled_name(self, column: str) -> str:
        name = column or "activity"
        if self._treat_logarithmically and not name.casefold().startswith("p"):
            return f"p{name}"
        return name

    def _format_activity(self, value: float | None) -> str:
        if value is None:
            return "—"
        shown = value
        if self._treat_logarithmically:
            shown = as_sali_activity(value, logarithmic=True)
            if shown is None:
                return "—"
        return f"{shown:.4g}"

    def _metrics_text(self, point: SaliPoint) -> str:
        similarity = f"Similarity = {point.similarity:.3f}"
        sali = f"SALI = {point.sali:.4g}"
        if point.delta_on is None or point.delta_off is None:
            delta = (
                f"Δ{self._scaled_name(self._activity_column)} = "
                f"{self._signed_text(point.signed_delta)}"
            )
            return f"{similarity}  ·  {delta}  ·  {sali}"
        on_name = self._scaled_name(self._activity_column or "on-target")
        off_name = self._scaled_name(self._off_target_column or "off-target")
        return (
            f"{similarity}  ·  "
            f"Δ{on_name} = {self._signed_text(point.delta_on)}  ·  "
            f"Δ{off_name} = {self._signed_text(point.delta_off)}  ·  "
            f"Δselectivity = {self._signed_text(point.signed_delta)}  ·  "
            f"{sali}"
        )

    def _activity_caption(self, oid: int, activity: float | None) -> str:
        on_name = self._scaled_name(self._activity_column or "Activity")
        on_text = self._format_activity(activity)
        if not self._off_target_column:
            return f"{on_name}: {on_text}"
        off = self._column_value_for_oid(oid, self._off_target_column)
        off_text = self._format_activity(off)
        lines = [
            f"{on_name}: {on_text}",
            f"{self._scaled_name(self._off_target_column)}: {off_text}",
        ]
        on_scaled = activity
        off_scaled = off
        if self._treat_logarithmically:
            on_scaled = None if activity is None else as_sali_activity(activity, logarithmic=True)
            off_scaled = None if off is None else as_sali_activity(off, logarithmic=True)
        if on_scaled is None or off_scaled is None:
            lines.append("Selectivity: —")
        else:
            lines.append(f"Selectivity: {on_scaled - off_scaled:.4g}")
        return "\n".join(lines)

    def _column_value_for_oid(self, oid: int, column: str) -> float | None:
        text = self._cell_text_for_oid(int(oid), column)
        if not text:
            return None
        try:
            return float(str(text).strip().replace(",", ""))
        except ValueError:
            return None

    def _update_molecule_panel(
        self,
        panel: dict[str, Any],
        oid: int,
        activity: float | None,
    ) -> None:
        label: QLabel = panel["struct"]
        panel["activity"].setText(self._activity_caption(oid, activity))
        mol = self._mol_for_oid(oid)
        pw, ph, dpr = self._preview_pixel_size(label)
        if mol is None:
            label.clear()
            label.setPixmap(QPixmap())
            label.setText("(no structure)")
            return

        from ...chem.depiction_coords import depiction_revision

        cache_key = (int(oid), pw, ph, depiction_revision(self._app))
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            pm = cached
        else:
            pm = self._render_mol(mol, pw, ph)
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

    def _render_mol(self, mol: Chem.Mol, pw: int, ph: int) -> QPixmap | None:
        try:
            return molecule_pixmap(mol, pw, ph)
        except Exception:
            return None
