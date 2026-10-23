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

"""Browse matched molecular pairs side-by-side with activity and highlights."""

from __future__ import annotations

from PyQt5.QtWidgets import QPushButton, QWidget
from rdkit import Chem

from ...analysis.mmp_analysis import MmpPair
from ...analysis.mmp_table import assemble_mmp_table_annotations
from .pair_browser import PairBrowserDialog


class MmpBrowserDialog(PairBrowserDialog):
    """Step through MMP pairs: two molecules, their activities, and table rows."""

    window_title = "Matched Molecular Pairs"
    select_status = "MMP pair"

    def __init__(
        self,
        parent,
        pairs: list[MmpPair],
        *,
        activity_column: str,
    ):
        self._all_pairs = list(pairs)
        self._pairs = list(pairs)
        super().__init__(parent, activity_column=activity_column)

    def _shows_pair_summary(self) -> bool:
        return False

    def _prepare_nav_extras(self) -> None:
        super()._prepare_nav_extras()
        self._btn_write = QPushButton("Write to table")
        self._btn_write.setToolTip(
            "Write MMP_Partners / MMP_Transforms / MMP_Delta columns for all pairs"
        )
        self._btn_write.clicked.connect(self._write_all_to_table)

    def _nav_trailing_widgets(self) -> list[QWidget]:
        return [self._btn_write, self._cb_selected_only]

    def _item_count(self) -> int:
        return len(self._pairs)

    def _current_pair_oids(self) -> tuple[int, int] | None:
        pair = self._current_pair()
        if pair is None:
            return None
        return (int(pair.oid_a), int(pair.oid_b))

    def set_pairs(self, pairs: list[MmpPair], *, activity_column: str | None = None) -> None:
        """Replace the pair list (e.g. when re-running MMP) and refresh the view."""
        self._all_pairs = list(pairs or [])
        if activity_column is not None:
            self._activity_column = activity_column
        prefer: tuple[int, int] | None = None
        if self._all_pairs:
            p0 = self._all_pairs[0]
            prefer = (int(p0.oid_a), int(p0.oid_b))
        self._prefer_keys = prefer
        self._preview_cache.clear()
        self._highlight_cache.clear()
        self._refresh_property_columns()
        self._rebuild_filtered_pairs(update_ui=True)

    def _on_selected_only_toggled(self, _checked: bool) -> None:
        cur = self._current_pair()
        if cur is not None:
            self._prefer_keys = (int(cur.oid_a), int(cur.oid_b))
        self._rebuild_filtered_pairs(update_ui=True)

    def _rebuild_filtered_pairs(self, *, update_ui: bool) -> None:
        source = list(self._all_pairs)
        if self._cb_selected_only.isChecked():
            selected = self._selected_oids()
            if selected:
                source = [p for p in source if int(p.oid_a) in selected or int(p.oid_b) in selected]
            else:
                source = []
        self._pairs = source
        prefer = self._prefer_keys
        self._idx = 0
        if prefer is not None:
            for i, p in enumerate(self._pairs):
                if (int(p.oid_a), int(p.oid_b)) == prefer:
                    self._idx = i
                    break
        if update_ui:
            self._update_ui()

    def _current_pair(self) -> MmpPair | None:
        if not self._pairs or not (0 <= self._idx < len(self._pairs)):
            return None
        return self._pairs[self._idx]

    def _write_all_to_table(self) -> None:
        app = self._app
        if app is None or not self._all_pairs:
            return
        rows, headers = assemble_mmp_table_annotations(
            self._all_pairs, activity_column=self._activity_column
        )
        if not rows:
            return
        try:
            app.on_calc_finished(rows, headers, progress_label="MMP")
        except Exception:
            pass

    def _refresh_previews(self) -> None:
        pair = self._current_pair()
        if pair is None:
            return
        mol_a = self._mol_for_oid(pair.oid_a, pair.smiles_a)
        mol_b = self._mol_for_oid(pair.oid_b, pair.smiles_b)
        ha, hb = self._variable_highlights((int(pair.oid_a), int(pair.oid_b)), mol_a, mol_b)
        self._show_molecule(
            self._left_panel,
            f"{self._activity_column}: {pair.activity_a:.4g}",
            mol_a,
            ha,
            (int(pair.oid_a), int(pair.oid_b), pair.transform, tuple(sorted(ha))),
        )
        self._show_molecule(
            self._right_panel,
            f"{self._activity_column}: {pair.activity_b:.4g}",
            mol_b,
            hb,
            (int(pair.oid_b), int(pair.oid_a), pair.transform, tuple(sorted(hb))),
        )

    def _update_ui(self) -> None:
        n = len(self._pairs)
        self._sync_nav_enabled(count=n, extra=[self._btn_write])
        if n <= 0:
            self._meta.setVisible(True)
            if self._cb_selected_only.isChecked():
                self._meta.setText(
                    "No matched molecular pairs involve the current table selection."
                )
            else:
                self._meta.setText("No matched molecular pairs found.")
            self._sync_pair_index(0)
            self._clear_pair_panels()
            self._update_property_values()
            return

        self._idx = max(0, min(self._idx, n - 1))
        self._meta.clear()
        self._meta.setVisible(False)
        self._sync_pair_index(n)
        self._refresh_previews()
        self._update_property_values()

    def _mol_for_oid(self, oid: int, fallback_smiles: str) -> Chem.Mol | None:
        app = self._app
        mol = None
        if app is not None:
            mol = getattr(app, "mols", {}).get(oid)
        if mol is not None and app is not None:
            from ...chem.depiction_coords import mol_for_app_depiction

            mol = mol_for_app_depiction(app, mol, int(oid))
        if mol is None and fallback_smiles:
            try:
                mol = Chem.MolFromSmiles(fallback_smiles)
            except Exception:
                mol = None
        return mol
