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

"""Column background coloring API for CompoundTableModel."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from ..table.column_color_compute import ColumnColorRule, color_rgb_for_value
from ..table.column_score_color import (
    COLOR_ALPHA,
    COLOR_FAVORABLE_RGB,
    COLOR_MID_RGB,
    COLOR_UNFAVORABLE_RGB,
    favorable_score_color_spec,
)


class CompoundTableColorMixin:
    def pending_color_cache_headers(self) -> list[str]:
        if not self._column_color_rules:
            return []
        return [h for h in self._column_color_rules if h not in self._pixmap_columns]

    def clear_column_coloring(self, header_name: str) -> None:
        """Disable background coloring for one column."""
        self._column_color_rules.pop(header_name, None)
        self._column_color_cache.pop(header_name, None)
        self._emit_color_refresh_for_header(header_name)

    def set_column_color_numeric_gradient(
        self,
        header_name: str,
        *,
        min_value: float,
        max_value: float,
        low_color: QColor,
        high_color: QColor,
        alpha: int = 96,
    ) -> None:
        """Color a data column by numeric value mapped onto a two-color gradient."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        if header_name in self._pixmap_columns:
            return
        lo = float(min(min_value, max_value))
        hi = float(max(min_value, max_value))
        a = max(20, min(int(alpha), 255))
        self._column_color_rules[header_name] = ColumnColorRule(
            mode="numeric",
            min_value=lo,
            max_value=hi,
            low_rgb=QColor(low_color).rgb(),
            high_rgb=QColor(high_color).rgb(),
            alpha=a,
        )
        self._rebuild_column_color_cache(header_name)
        self._emit_color_refresh_for_header(header_name)

    def set_column_color_three_point_gradient(
        self,
        header_name: str,
        *,
        min_value: float,
        mid_value: float,
        max_value: float,
        low_color: QColor,
        mid_color: QColor,
        high_color: QColor,
        alpha: int = 96,
    ) -> None:
        """Color numeric values with low/mid/high anchors."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        if header_name in self._pixmap_columns:
            return
        lo = float(min_value)
        mid = float(mid_value)
        hi = float(max_value)
        if hi < lo:
            lo, hi = hi, lo
        mid = max(lo, min(mid, hi))
        a = max(20, min(int(alpha), 255))
        self._column_color_rules[header_name] = ColumnColorRule(
            mode="numeric3",
            min_value=lo,
            mid_value=mid,
            max_value=hi,
            low_rgb=QColor(low_color).rgb(),
            mid_rgb=QColor(mid_color).rgb(),
            high_rgb=QColor(high_color).rgb(),
            alpha=a,
        )
        self._rebuild_column_color_cache(header_name)
        self._emit_color_refresh_for_header(header_name)

    def apply_favorable_score_column_coloring(self, header_name: str) -> bool:
        """Color QED / AB-MPS / BBB / CNS MPO columns green (favorable) → yellow → red."""
        spec = favorable_score_color_spec(header_name)
        if spec is None:
            return False
        green = QColor(*COLOR_FAVORABLE_RGB)
        yellow = QColor(*COLOR_MID_RGB)
        red = QColor(*COLOR_UNFAVORABLE_RGB)
        if spec.higher_is_better:
            low_color, mid_color, high_color = red, yellow, green
        else:
            low_color, mid_color, high_color = green, yellow, red
        self.set_column_color_three_point_gradient(
            header_name,
            min_value=spec.min_value,
            mid_value=spec.mid_value,
            max_value=spec.max_value,
            low_color=low_color,
            mid_color=mid_color,
            high_color=high_color,
            alpha=COLOR_ALPHA,
        )
        return self.column_color_mode(header_name) == "numeric3"

    def set_column_color_categorical(self, header_name: str, *, alpha: int = 88) -> None:
        """Color non-empty distinct text values using a deterministic categorical palette."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        if header_name in self._pixmap_columns:
            return
        a = max(20, min(int(alpha), 255))
        self._column_color_rules[header_name] = ColumnColorRule(mode="categorical", alpha=a)
        self._rebuild_column_color_cache(header_name)
        self._emit_color_refresh_for_header(header_name)

    def column_color_mode(self, header_name: str) -> str:
        rule = self._column_color_rules.get(header_name)
        return "" if rule is None else rule.mode

    def column_color_rule_spec(self, header_name: str) -> dict | None:
        rule = self._column_color_rules.get(header_name)
        if rule is None:
            return None
        out = {
            "mode": rule.mode,
            "alpha": int(rule.alpha),
        }
        if rule.mode in {"numeric", "numeric3"}:
            out["min"] = float(rule.min_value)
            out["max"] = float(rule.max_value)
            out["low_rgb"] = int(rule.low_rgb)
            out["high_rgb"] = int(rule.high_rgb)
        if rule.mode == "numeric3":
            out["mid"] = float(rule.mid_value)
            out["mid_rgb"] = int(rule.mid_rgb)
        return out

    def export_column_color_rules(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for header in sorted(self._column_color_rules.keys()):
            spec = self.column_color_rule_spec(header)
            if spec is not None:
                out[header] = spec
        return out

    def restore_column_color_rules(self, spec_by_header: dict) -> None:
        if not isinstance(spec_by_header, dict):
            return
        for header_name, spec in spec_by_header.items():
            if not isinstance(header_name, str) or not isinstance(spec, dict):
                continue
            mode = str(spec.get("mode") or "")
            if mode == "numeric":
                self.set_column_color_numeric_gradient(
                    header_name,
                    min_value=float(spec.get("min", 0.0)),
                    max_value=float(spec.get("max", 1.0)),
                    low_color=QColor.fromRgb(int(spec.get("low_rgb", QColor(48, 119, 242).rgb()))),
                    high_color=QColor.fromRgb(int(spec.get("high_rgb", QColor(236, 73, 73).rgb()))),
                    alpha=int(spec.get("alpha", 96)),
                )
            elif mode == "numeric3":
                self.set_column_color_three_point_gradient(
                    header_name,
                    min_value=float(spec.get("min", 0.0)),
                    mid_value=float(spec.get("mid", 0.5)),
                    max_value=float(spec.get("max", 1.0)),
                    low_color=QColor.fromRgb(int(spec.get("low_rgb", QColor(48, 119, 242).rgb()))),
                    mid_color=QColor.fromRgb(int(spec.get("mid_rgb", QColor(245, 209, 84).rgb()))),
                    high_color=QColor.fromRgb(int(spec.get("high_rgb", QColor(236, 73, 73).rgb()))),
                    alpha=int(spec.get("alpha", 96)),
                )
            elif mode == "categorical":
                self.set_column_color_categorical(header_name, alpha=int(spec.get("alpha", 88)))

    def _emit_color_refresh_for_header(self, header_name: str) -> None:
        if header_name not in self._headers:
            return
        n = len(self._rows)
        if n <= 0:
            return
        col = self._headers.index(header_name)
        self.dataChanged.emit(self.index(0, col), self.index(n - 1, col), [Qt.BackgroundRole])

    def _refresh_color_cache_for_cell(self, row_obj: object, header_name: str, value: str) -> None:
        rule = self._column_color_rules.get(header_name)
        if rule is None:
            return
        cmap = self._column_color_cache.setdefault(header_name, {})
        rgb = self._color_rgb_for_value(rule, value)
        if rgb is None:
            cmap.pop(row_obj.oid, None)
        else:
            cmap[row_obj.oid] = rgb

    def _refresh_color_cache_for_row(self, row_obj: object, row_cells: dict[str, str]) -> None:
        if not self._column_color_rules:
            return
        for header_name in self._column_color_rules:
            if header_name in self._pixmap_columns:
                continue
            val = row_cells.get(header_name, "")
            self._refresh_color_cache_for_cell(row_obj, header_name, val)

    def _rebuild_column_color_cache(self, header_name: str) -> None:
        rule = self._column_color_rules.get(header_name)
        if rule is None:
            self._column_color_cache.pop(header_name, None)
            return
        cmap: dict[int, int] = {}
        for row in self._rows:
            rgb = self._color_rgb_for_value(rule, row.values.get(header_name, ""))
            if rgb is not None:
                cmap[row.oid] = rgb
        self._column_color_cache[header_name] = cmap

    def _color_rgb_for_value(self, rule: ColumnColorRule, raw_value: str) -> int | None:
        return color_rgb_for_value(rule, raw_value)
