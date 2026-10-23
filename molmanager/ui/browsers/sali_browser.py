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

"""Browse SALI pairs side-by-side, highlighting atoms outside the shared core."""

from __future__ import annotations

from rdkit import Chem

from ...analysis.sali_analysis import SaliPoint, as_sali_activity
from .pair_browser import PairBrowserDialog


class SaliBrowserDialog(PairBrowserDialog):
    """Step through SALI pairs: two molecules, activities, similarity, and SALI."""

    window_title = "SALI Pairs"
    select_status = "SALI pair"

    def __init__(
        self,
        parent,
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
        super().__init__(parent, activity_column=activity_column)

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
        self._highlight_cache.clear()
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
        mol_a = self._mol_for_oid(point.oid_a)
        mol_b = self._mol_for_oid(point.oid_b)
        ha, hb = self._variable_highlights((int(point.oid_a), int(point.oid_b)), mol_a, mol_b)
        self._show_molecule(
            self._left_panel,
            self._activity_caption(point.oid_a, self._activity_for_oid(point.oid_a)),
            mol_a,
            ha,
            (int(point.oid_a), int(point.oid_b), tuple(sorted(ha))),
        )
        self._show_molecule(
            self._right_panel,
            self._activity_caption(point.oid_b, self._activity_for_oid(point.oid_b)),
            mol_b,
            hb,
            (int(point.oid_b), int(point.oid_a), tuple(sorted(hb))),
        )

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
        self._refresh_previews()
        self._update_property_values()

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
