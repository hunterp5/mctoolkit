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

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from ...analysis.mmp_analysis import MmpPair, canonicalize_pair_direction
from ...analysis.mmp_depict import highlight_atoms_for_pair
from ...analysis.mmp_table import assemble_mmp_table_annotations
from .chrome import configure_browser_mol_drawer, style_browser_emphasis_label
from .pair_browser import PairBrowserDialog


class MmpBrowserDialog(PairBrowserDialog):
    """Step through MMP pairs: two molecules, activities, Δactivity, and table properties."""

    window_title = "Matched Molecular Pairs"
    select_status = "MMP pair"

    def __init__(
        self,
        parent: Any,
        pairs: list[MmpPair],
        *,
        activity_column: str,
    ):
        self._all_pairs = list(pairs)
        self._pairs = list(pairs)
        self._highlight_cache: dict[tuple[int, int], tuple[list[int], list[int]]] = {}
        super().__init__(parent, activity_column=activity_column)

    def _populate_header(self, root: QVBoxLayout) -> None:
        self._transform_preview = QLabel()
        self._transform_preview.setAlignment(Qt.AlignCenter)
        self._transform_preview.setMinimumHeight(72)
        self._transform_preview.setMaximumHeight(88)
        self._transform_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self._transform_preview)

        self._delta_label = QLabel()
        self._delta_label.setAlignment(Qt.AlignCenter)
        self._delta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._delta_label.setWordWrap(True)
        style_browser_emphasis_label(self._delta_label)
        root.addWidget(self._delta_label)

    def _prepare_nav_extras(self) -> None:
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
        self._update_molecule_panel(self._left_panel, pair.oid_a, pair.activity_a, pair, side="a")
        self._update_molecule_panel(self._right_panel, pair.oid_b, pair.activity_b, pair, side="b")

    def _update_ui(self) -> None:
        n = len(self._pairs)
        self._sync_nav_enabled(count=n, extra=[self._btn_write])
        if n <= 0:
            if self._cb_selected_only.isChecked():
                self._meta.setText(
                    "No matched molecular pairs involve the current table selection."
                )
            else:
                self._meta.setText("No matched molecular pairs found.")
            self._delta_label.setText("")
            self._transform_preview.clear()
            self._transform_preview.setPixmap(QPixmap())
            self._transform_preview.setToolTip("")
            self._clear_pair_panels()
            self._update_property_values()
            return

        self._idx = max(0, min(self._idx, n - 1))
        pair = self._pairs[self._idx]
        self._meta.setText(f"Pair {self._idx + 1} of {n}")
        sign = "+" if pair.delta_activity >= 0 else ""
        canon_transform, side_from, side_to, _cd = canonicalize_pair_direction(pair)
        self._delta_label.setText(
            f"Δ{self._activity_column} = {sign}{pair.delta_activity:.4g}  "
            f"({pair.activity_a:.4g} → {pair.activity_b:.4g})"
        )
        self._delta_label.setToolTip(canon_transform)
        self._update_transform_preview(side_from, side_to, canon_transform)
        self._left_panel["box"].setTitle(f"Molecule A  (ID {pair.oid_a})")
        self._right_panel["box"].setTitle(f"Molecule B  (ID {pair.oid_b})")
        self._refresh_previews()
        self._update_property_values()

    def _update_transform_preview(self, side_from: str, side_to: str, transform: str) -> None:
        frag_w, frag_h, arrow_w = 96, 64, 28
        left = self._render_frag_smiles(side_from, frag_w, frag_h)
        right = self._render_frag_smiles(side_to, frag_w, frag_h)
        if left is None and right is None:
            self._transform_preview.clear()
            self._transform_preview.setPixmap(QPixmap())
            self._transform_preview.setText("→")
            self._transform_preview.setToolTip(transform)
            return
        if left is None:
            left = QPixmap(frag_w, frag_h)
            left.fill(Qt.transparent)
        if right is None:
            right = QPixmap(frag_w, frag_h)
            right.fill(Qt.transparent)
        out = QPixmap(frag_w + arrow_w + frag_w, frag_h)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            painter.drawPixmap(0, 0, left)
            painter.setPen(self.palette().color(self.palette().WindowText))
            painter.drawText(frag_w, 0, arrow_w, frag_h, Qt.AlignCenter, "→")
            painter.drawPixmap(frag_w + arrow_w, 0, right)
        finally:
            painter.end()
        dpr = max(1.0, float(self.devicePixelRatioF()))
        out.setDevicePixelRatio(dpr)
        self._transform_preview.setPixmap(out)
        self._transform_preview.setText("")
        self._transform_preview.setToolTip(transform)

    def _render_frag_smiles(self, smiles: str, pw: int, ph: int) -> QPixmap | None:
        if not smiles:
            return None
        cache_key = ("frag", smiles, pw, ph)
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            return cached
        try:
            mol = Chem.MolFromSmiles(smiles)
        except Exception:
            mol = None
        if mol is None:
            return None
        pm = self._render_highlighted(mol, pw, ph, [])
        if pm is not None and not pm.isNull():
            self._preview_cache[cache_key] = pm
        return pm

    def _highlights_for_pair(self, pair: MmpPair) -> tuple[list[int], list[int]]:
        key = (pair.oid_a, pair.oid_b)
        cached = self._highlight_cache.get(key)
        if cached is not None:
            return cached
        mol_a = self._mol_for_oid(pair.oid_a, pair.smiles_a)
        mol_b = self._mol_for_oid(pair.oid_b, pair.smiles_b)
        ha, hb = highlight_atoms_for_pair(mol_a, mol_b) if mol_a and mol_b else ([], [])
        self._highlight_cache[key] = (ha, hb)
        return ha, hb

    def _mol_for_oid(self, oid: int, fallback_smiles: str) -> Chem.Mol | None:
        app = self._app
        mol = None
        if app is not None:
            mol = getattr(app, "mols", {}).get(oid)
        if mol is None and fallback_smiles:
            try:
                mol = Chem.MolFromSmiles(fallback_smiles)
            except Exception:
                mol = None
        return mol

    def _update_molecule_panel(
        self,
        panel: dict[str, Any],
        oid: int,
        activity: float,
        pair: MmpPair,
        *,
        side: str,
    ) -> None:
        label: QLabel = panel["struct"]
        panel["activity"].setText(f"{self._activity_column}: {activity:.4g}")
        smiles = pair.smiles_a if side == "a" else pair.smiles_b
        mol = self._mol_for_oid(oid, smiles)
        pw, ph, dpr = self._preview_pixel_size(label)
        if mol is None:
            label.clear()
            label.setPixmap(QPixmap())
            label.setText("(no structure)")
            return

        ha, hb = self._highlights_for_pair(pair)
        highlight = ha if side == "a" else hb
        highlight_key = tuple(sorted(highlight))
        cache_key = (oid, pw, ph, pair.oid_a, pair.oid_b, pair.transform, highlight_key)
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            pm = cached
        else:
            pm = self._render_highlighted(mol, pw, ph, highlight)
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

    def _render_highlighted(
        self,
        mol: Chem.Mol,
        pw: int,
        ph: int,
        highlight_atoms: list[int],
    ) -> QPixmap | None:
        try:
            drawer = rdMolDraw2D.MolDraw2DCairo(pw, ph)
            configure_browser_mol_drawer(drawer, pw)
            highlight_set = set(int(i) for i in highlight_atoms)
            colors = {i: (0.95, 0.55, 0.15) for i in highlight_set}
            if highlight_set:
                rdMolDraw2D.PrepareAndDrawMolecule(
                    drawer,
                    mol,
                    highlightAtoms=list(highlight_set),
                    highlightAtomColors=colors,
                )
            else:
                rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
            drawer.FinishDrawing()
            img = QImage.fromData(drawer.GetDrawingText())
            return QPixmap.fromImage(img)
        except Exception:
            return None
