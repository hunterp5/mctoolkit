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

"""Modeless SOM results browser: step through FAME3R maps like Data → Browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from PyQt5.QtCore import QEvent, QRect, Qt, QTimer
from PyQt5.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    browser_structure_preview_width,
)
from ...predictions.som_prediction import (
    SOM_CANCELLED_ERROR,
    SOM_MAP_COLUMN,
    SOM_P1_SITES_COLUMN,
    SOM_P2_SITES_COLUMN,
    SOM_PHASE_COLUMN,
    SOM_PROB_COLUMN,
    SOM_SITES_COLUMN,
    SomAtomHit,
    is_som_map_header,
    render_som_map_png,
    som_phase_label,
    som_probability_rgb,
)
from ..dockable_plot import (
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_send_window_button,
    add_centered_browser_nav,
    style_browser_nav_buttons,
    sync_footer_on_parent_change,
)
from ..strings import TOOL_PREDICT_SOM
from ..widgets import NumericTableWidgetItem
from .chrome import (
    BrowserHostDialog,
    apply_browser_body_layout,
    install_browser_nav_shortcuts,
    style_browser_data_table,
    style_browser_preview_host,
    style_browser_structure_label,
)


@dataclass(frozen=True)
class SomBrowseRecord:
    """One molecule in the SOM results browser."""

    oid: int | None
    smiles: str
    atoms: tuple[SomAtomHit, ...] = ()
    error: str | None = None
    columns: dict[str, str] = field(default_factory=dict)


def records_from_worker_rows(
    rows: Sequence, *, include_cancelled: bool = False
) -> list[SomBrowseRecord]:
    """Convert Predict SOM worker tuples into browser records.

    Cancelled placeholders are omitted by default so the browser only shows
    molecules that actually returned a result.
    """
    out: list[SomBrowseRecord] = []
    for row in rows or ():
        if not row:
            continue
        oid, cols, _png, atoms, _headers = row[:5]
        col_d = dict(cols or {})
        hits = tuple(hit for hit in (_coerce_atom_hit(a) for a in (atoms or ())) if hit is not None)
        raw_map = str(col_d.get(SOM_MAP_COLUMN) or "").strip()
        smiles = raw_map if _looks_like_smiles(raw_map) else ""
        err = None
        if not hits:
            err = raw_map if not smiles else "No SOM atoms were returned."
            if not err:
                err = "No SOM atoms were returned."
        out.append(
            SomBrowseRecord(
                oid=None if oid is None else int(oid),
                smiles=smiles,
                atoms=hits,
                error=err,
                columns=col_d,
            )
        )
    if include_cancelled:
        return out
    return [r for r in out if r.error != SOM_CANCELLED_ERROR]


def _atoms_have_phases(atoms: Sequence[SomAtomHit]) -> bool:
    return any(hit.is_phase1_som is not None or hit.is_phase2_som is not None for hit in atoms)


def _looks_like_smiles(text: str) -> bool:
    t = (text or "").strip()
    if not t or t.upper() == "N/A" or t == SOM_CANCELLED_ERROR or " " in t:
        return False
    if t.startswith("No ") or "failed" in t.lower() or "error" in t.lower():
        return False
    return True


def _coerce_atom_hit(item: Any) -> SomAtomHit | None:
    if isinstance(item, SomAtomHit):
        return item
    if isinstance(item, dict):
        try:
            return SomAtomHit(
                atom_id=int(item["atom_id"]),
                probability=float(item["probability"]),
                is_som=bool(item.get("is_som")),
                fame_score=item.get("fame_score"),
                shannon_entropy=item.get("shannon_entropy"),
                is_phase1_som=item.get("is_phase1_som"),
                is_phase2_som=item.get("is_phase2_som"),
                phase1_probability=item.get("phase1_probability"),
                phase2_probability=item.get("phase2_probability"),
            )
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _qcolor_from_rgb(rgb: tuple[float, float, float]) -> QColor:
    r, g, b = rgb
    return QColor.fromRgbF(
        min(max(float(r), 0.0), 1.0),
        min(max(float(g), 0.0), 1.0),
        min(max(float(b), 0.0), 1.0),
    )


def _parse_int_list(text: str) -> list[int]:
    out: list[int] = []
    for part in (text or "").replace("—", ",").split(","):
        token = part.strip()
        if token.isdigit():
            out.append(int(token))
    return out


def _atoms_from_som_columns(cols: dict[str, str]) -> tuple[SomAtomHit, ...]:
    """Rebuild atom hits from table SOM text columns when worker atoms are gone."""
    sites = set(_parse_int_list(cols.get(SOM_SITES_COLUMN, "")))
    p1_sites = set(_parse_int_list(cols.get(SOM_P1_SITES_COLUMN, "")))
    p2_sites = set(_parse_int_list(cols.get(SOM_P2_SITES_COLUMN, "")))
    has_phases = bool(p1_sites or p2_sites or (cols.get(SOM_PHASE_COLUMN) or "").strip())
    phase_map: dict[int, str] = {}
    for bit in (cols.get(SOM_PHASE_COLUMN) or "").split(";"):
        bit = bit.strip()
        if ":" not in bit:
            continue
        aid, lab = bit.split(":", 1)
        if aid.strip().isdigit():
            phase_map[int(aid.strip())] = lab.strip()
    by_id: dict[int, SomAtomHit] = {}
    probs_txt = (cols.get(SOM_PROB_COLUMN) or "").replace("…", "").replace("...", "")
    for bit in probs_txt.split(";"):
        bit = bit.strip()
        if ":" not in bit:
            continue
        aid, raw_p = bit.split(":", 1)
        if not aid.strip().isdigit():
            continue
        try:
            atom_id = int(aid.strip())
            probability = float(raw_p.strip())
        except ValueError:
            continue
        lab = phase_map.get(atom_id, "")
        is_p1 = atom_id in p1_sites or "P1" in lab if has_phases else None
        is_p2 = atom_id in p2_sites or "P2" in lab if has_phases else None
        by_id[atom_id] = SomAtomHit(
            atom_id=atom_id,
            probability=probability,
            is_som=atom_id in sites,
            is_phase1_som=is_p1,
            is_phase2_som=is_p2,
        )
    for atom_id in sites | p1_sites | p2_sites:
        if atom_id in by_id:
            continue
        lab = phase_map.get(atom_id, "")
        by_id[atom_id] = SomAtomHit(
            atom_id=atom_id,
            probability=0.0,
            is_som=True,
            is_phase1_som=atom_id in p1_sites or "P1" in lab if has_phases else None,
            is_phase2_som=atom_id in p2_sites or "P2" in lab if has_phases else None,
        )
    return tuple(sorted(by_id.values(), key=lambda a: (-a.probability, a.atom_id)))


def records_from_table(app: Any) -> list[SomBrowseRecord]:
    """Rebuild browser records from Predict SOM table columns."""
    model = getattr(app, "_table_model", None)
    headers = list(getattr(app, "headers", None) or [])
    if model is None or not headers:
        return []
    map_headers = [h for h in headers if is_som_map_header(h)]
    if not map_headers:
        return []
    map_h = map_headers[0]
    som_headers = [h for h in headers if str(h).strip().lower().startswith("som ")]
    out: list[SomBrowseRecord] = []
    n = int(model.rowCount())
    for row in range(n):
        try:
            oid = int(model.row_oid(row))
        except (TypeError, ValueError):
            continue
        cols = {h: str(model.backing_value_for_row_header(row, h) or "") for h in som_headers}
        raw_map = str(cols.get(map_h) or "").strip()
        smiles = raw_map if _looks_like_smiles(raw_map) else ""
        if not smiles:
            smiles = str(model.backing_value_for_row_header(row, "SMILES") or "").strip()
        if not smiles:
            mols = getattr(app, "mols", None) or {}
            mol = mols.get(oid)
            if mol is not None:
                from ...chem.molecule_conversion import mol_to_canonical_smiles

                smiles = mol_to_canonical_smiles(mol) or ""
        atoms = _atoms_from_som_columns(cols)
        err = None
        if not atoms and not smiles:
            err = raw_map if raw_map else "No SOM atoms were returned."
            if err.upper() == "N/A":
                continue
        out.append(
            SomBrowseRecord(
                oid=oid,
                smiles=smiles,
                atoms=atoms,
                error=err if not atoms else None,
                columns=cols,
            )
        )
    return [r for r in out if r.error != SOM_CANCELLED_ERROR]


def _atom_hit_to_json(hit: SomAtomHit) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "atom_id": int(hit.atom_id),
        "probability": float(hit.probability),
        "is_som": bool(hit.is_som),
    }
    if hit.fame_score is not None:
        payload["fame_score"] = float(hit.fame_score)
    if hit.shannon_entropy is not None:
        payload["shannon_entropy"] = float(hit.shannon_entropy)
    if hit.is_phase1_som is not None:
        payload["is_phase1_som"] = bool(hit.is_phase1_som)
    if hit.is_phase2_som is not None:
        payload["is_phase2_som"] = bool(hit.is_phase2_som)
    if hit.phase1_probability is not None:
        payload["phase1_probability"] = float(hit.phase1_probability)
    if hit.phase2_probability is not None:
        payload["phase2_probability"] = float(hit.phase2_probability)
    return payload


def serialize_som_browse_records(records: Sequence[SomBrowseRecord] | None) -> list[dict[str, Any]]:
    """JSON-safe SOM browser payload for ``.cms`` session files."""
    out: list[dict[str, Any]] = []
    for rec in records or ():
        item: dict[str, Any] = {
            "oid": rec.oid,
            "smiles": rec.smiles,
            "atoms": [_atom_hit_to_json(hit) for hit in rec.atoms],
        }
        if rec.error:
            item["error"] = rec.error
        out.append(item)
    return out


def deserialize_som_browse_records(raw: Any) -> list[SomBrowseRecord]:
    """Rebuild browser records from a session ``som_browse`` list."""
    if not isinstance(raw, list):
        return []
    out: list[SomBrowseRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        oid_raw = item.get("oid")
        try:
            oid = None if oid_raw is None else int(oid_raw)
        except (TypeError, ValueError):
            continue
        atoms = tuple(
            hit
            for hit in (_coerce_atom_hit(a) for a in (item.get("atoms") or ()))
            if hit is not None
        )
        out.append(
            SomBrowseRecord(
                oid=oid,
                smiles=str(item.get("smiles") or ""),
                atoms=atoms,
                error=item.get("error"),
            )
        )
    return out


def restore_som_maps_for_session(app: Any, sidecar: Any = None) -> int:
    """Register SOM Map columns, restore browse records, and redraw table maps.

    Returns the number of map images written.
    """
    sidecar_records = deserialize_som_browse_records(sidecar)
    records = sidecar_records or records_from_table(app)
    app._som_browse_records = list(records)
    headers = list(getattr(app, "headers", None) or [])
    map_headers = [h for h in headers if is_som_map_header(h)]
    if not map_headers:
        return 0
    model = getattr(app, "_table_model", None)
    if model is None:
        return 0
    from ...table.structure_depiction_layout import structure_depict_height, structure_depict_width
    from ...table.structure_image import pixmap_from_structure_image

    for header in map_headers:
        model.register_pixmap_column(header)
    dw, dh = structure_depict_width(), structure_depict_height()
    rec_by_oid = {int(rec.oid): rec for rec in records if rec.oid is not None}
    mols = getattr(app, "mols", None) or {}
    last_pm = None
    drawn = 0
    n = int(model.rowCount())
    sidecar_oids = set(rec_by_oid) if sidecar_records else None
    for row in range(n):
        try:
            oid = int(model.row_oid(row))
        except (TypeError, ValueError):
            continue
        if sidecar_oids is not None and oid not in sidecar_oids:
            continue
        rec = rec_by_oid.get(oid)
        smiles = rec.smiles if rec is not None else ""
        atoms = rec.atoms if rec is not None else ()
        if not smiles:
            smiles = str(model.backing_value_for_row_header(row, map_headers[0]) or "").strip()
        if not smiles or (rec is not None and rec.error and not atoms):
            continue
        png = render_som_map_png(
            smiles,
            atoms,
            width=dw,
            height=dh,
            reference_mol=mols.get(oid),
        )
        if not png:
            continue
        pm = pixmap_from_structure_image(png, dw, dh)
        if pm is None or pm.isNull():
            continue
        for header in map_headers:
            model.set_column_pixmap(oid, header, pm)
        last_pm = pm
        drawn += 1
        view_row = row
        resolve = getattr(app, "_resolve_structure_row_for_oid", None)
        if callable(resolve):
            found = resolve(oid)
            if found != -1:
                view_row = int(found)
        need_h = max(dh, int(pm.height()))
        table = getattr(app, "table", None)
        if table is not None and int(table.rowHeight(view_row)) < need_h:
            table.setRowHeight(int(view_row), need_h)
    sync_w = getattr(app, "_sync_data_pixmap_column_width", None)
    if callable(sync_w) and last_pm is not None:
        sync_w(map_headers[0], last_pm, dw)
    return drawn


class SomColorScaleWidget(QWidget):
    """Vertical SOM probability scale (yellow low → red high)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(68)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setToolTip("SOM probability: yellow (low) to red (high).")

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(255, 255, 255))
        text = QColor(40, 40, 40)
        edge = QColor(180, 180, 180)
        font = self.font()
        font.setPointSize(max(7, font.pointSize() - 1))
        painter.setFont(font)
        fm = painter.fontMetrics()
        width = self.width()
        height = self.height()
        pad = 8
        bar_top = pad
        bar_bottom = height - pad
        bar_h = max(48, bar_bottom - bar_top)
        bar_w = 14
        bar_x = 8
        bar = QRect(bar_x, bar_top, bar_w, bar_h)
        gradient = QLinearGradient(0, bar.top(), 0, bar.bottom())
        for stop in (0.0, 0.25, 0.5, 0.75, 1.0):
            gradient.setColorAt(stop, _qcolor_from_rgb(som_probability_rgb(1.0 - stop)))
        painter.fillRect(bar, gradient)
        painter.setPen(QPen(edge))
        painter.drawRect(bar.adjusted(0, 0, -1, -1))
        painter.setPen(QPen(text))
        label_x = bar.right() + 4
        label_w = max(16, width - label_x - 2)
        for label, frac in (("1.0", 0.0), ("0.5", 0.5), ("0.0", 1.0)):
            y = bar.top() + int(frac * (bar.height() - 1)) - fm.height() // 2
            painter.drawText(
                QRect(label_x, y, label_w, fm.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )
        painter.end()


class SomBrowserWidget(QWidget):
    """Forward/back through SOM maps with a Data → Browser style preview."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = f"{TOOL_PREDICT_SOM} Browser"
        self._records: list[SomBrowseRecord] = []
        self._all_records: list[SomBrowseRecord] = []
        self._idx = 0
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._emphasized_atom: int | None = None
        self._connected_selection_store = None

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._meta.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        self._struct_label = QLabel()
        self._struct_label.setMinimumSize(
            browser_structure_preview_width() // 2,
            BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2,
        )
        self._struct_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._struct_label.setMargin(0)
        self._struct_label.setIndent(0)
        style_browser_structure_label(self._struct_label)
        self._preview_host = QWidget(self)
        self._preview_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        style_browser_preview_host(self._preview_host)
        self._color_scale = SomColorScaleWidget(self._preview_host)
        self._color_scale.setAutoFillBackground(True)
        pal = self._color_scale.palette()
        pal.setColor(self._color_scale.backgroundRole(), QColor(255, 255, 255))
        self._color_scale.setPalette(pal)
        preview_row = QHBoxLayout(self._preview_host)
        preview_row.setContentsMargins(0, 0, 0, 0)
        preview_row.setSpacing(0)
        preview_row.addWidget(self._struct_label, 1)
        preview_row.addWidget(self._color_scale, 0)
        root.addWidget(self._preview_host, 1)

        self._atom_table = QTableWidget(0, 4)
        self._atom_table.setHorizontalHeaderLabels(["Atom", "Probability", "SOM", "Entropy"])
        self._atom_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._atom_table.verticalHeader().setVisible(False)
        self._atom_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._atom_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._atom_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._atom_table.setToolTip(
            "Select an atom to highlight it on the 2D map. Click a column header to sort."
        )
        self._atom_table.setMaximumHeight(180)
        self._atom_table.setFixedHeight(180)
        self._atom_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        style_browser_data_table(self._atom_table)
        self._atom_sort_header: str | None = None
        self._atom_sort_order = Qt.AscendingOrder
        self._atom_table.setSortingEnabled(True)
        hdr = self._atom_table.horizontalHeader()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.setSortIndicator(-1, Qt.AscendingOrder)
        hdr.sortIndicatorChanged.connect(self._on_atom_sort_changed)
        self._atom_table.itemSelectionChanged.connect(self._on_atom_selection_changed)
        root.addWidget(self._atom_table)

        self._nav_bar = QWidget(self)
        self._nav_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row_btns = QHBoxLayout(self._nav_bar)
        row_btns.setContentsMargins(0, 0, 0, 0)
        row_btns.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First molecule (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous molecule (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next molecule (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last molecule (End)")
        self._btn_select = QPushButton()
        self._btn_select.setToolTip("Select this row in the compound table")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
            self._btn_select,
        )
        self._cb_only_selected = QCheckBox("Browse Only Selected")
        self._cb_only_selected.setToolTip(
            "When checked, this browser walks only table rows that are currently selected."
        )
        self._cb_only_selected.toggled.connect(self._on_only_selected_toggled)
        add_centered_browser_nav(
            row_btns,
            [
                self._btn_first,
                self._btn_back,
                self._btn_fwd,
                self._btn_last,
                self._btn_select,
            ],
            trailing=self._cb_only_selected,
        )
        root.addWidget(self._nav_bar)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        foot.addWidget(self._meta)
        foot.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this browser beside the compound table.",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        foot.addWidget(self._add_to_main_btn)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked browser in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        foot.addWidget(self._send_window_btn)
        root.insertWidget(0, self._footer_bar)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_select.clicked.connect(self._select_current_row)

        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_preview)
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(80)
        self._selection_timer.timeout.connect(self._refresh_selected_scope)

        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())
        self._connect_table_selection()
        self._update_ui()

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self._disconnect_table_selection()
        self.parent_app = parent_app
        self._app = parent_app
        self._connect_table_selection()

    def embedded_minimum_width(self) -> int:
        return max(360, browser_structure_preview_width() // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 480)

    def create_floating_dialog(self, parent_app) -> "SomBrowserDialog":
        self.show()
        return SomBrowserDialog(parent_app, panel=self)

    def set_records(self, records: list[SomBrowseRecord]) -> None:
        self._all_records = list(records or [])
        self._preview_cache.clear()
        has_oid = any(r.oid is not None for r in self._all_records)
        self._cb_only_selected.setEnabled(has_oid)
        self._apply_record_scope(preserve_oid=False)

    def jump_to_oid(self, oid: int | None) -> bool:
        """Show the record for ``oid``, turning off selected-only if needed."""
        if oid is None:
            return False
        want = int(oid)
        if not any(r.oid == want for r in self._all_records):
            return False
        if self._cb_only_selected.isChecked():
            self._cb_only_selected.blockSignals(True)
            self._cb_only_selected.setChecked(False)
            self._cb_only_selected.blockSignals(False)
        self._records = list(self._all_records)
        for i, rec in enumerate(self._records):
            if rec.oid == want:
                self._idx = i
                self._update_ui()
                return True
        return False

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, SomBrowserDialog):
            discard_host_dialog_after_dock(dlg, self.parent_app, "_som_browser_dialog")

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return False

    def _sync_footer_chrome(self) -> None:
        from ..dockable_plot import apply_plot_chrome_glyphs, sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), SomBrowserDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)

    def event(self, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        return super().event(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        timer = getattr(self, "_resize_timer", None)
        if timer is not None:
            timer.start()

    def _current(self) -> SomBrowseRecord | None:
        if not self._records or not (0 <= self._idx < len(self._records)):
            return None
        return self._records[self._idx]

    def _go_first(self) -> None:
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._idx = max(0, len(self._records) - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        if not self._records:
            return
        self._idx = (self._idx + int(delta)) % len(self._records)
        self._update_ui()

    def _on_only_selected_toggled(self, _checked: bool = False) -> None:
        self._apply_record_scope(preserve_oid=True)

    def _selected_oids(self) -> frozenset[int]:
        store = self._selection_store_or_none()
        return store.oids if store is not None else frozenset()

    def _selection_store_or_none(self):
        return getattr(self._app, "selection_store", None) if self._app is not None else None

    def _apply_record_scope(self, *, preserve_oid: bool) -> None:
        cur_oid = None
        if preserve_oid:
            rec = self._current()
            if rec is not None and rec.oid is not None:
                cur_oid = int(rec.oid)
        recs = list(self._all_records)
        if self._cb_only_selected.isChecked():
            selected = self._selected_oids()
            recs = [r for r in recs if r.oid is not None and int(r.oid) in selected]
        self._records = recs
        self._idx = 0
        if cur_oid is not None:
            for i, rec in enumerate(self._records):
                if rec.oid == cur_oid:
                    self._idx = i
                    break
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

    def _on_table_selection_changed(self, _origin: object = None) -> None:
        if not self._cb_only_selected.isChecked():
            return
        timer = getattr(self, "_selection_timer", None)
        if timer is not None:
            timer.start()

    def _refresh_selected_scope(self) -> None:
        if self._cb_only_selected.isChecked():
            self._apply_record_scope(preserve_oid=True)

    def _select_current_row(self) -> None:
        rec = self._current()
        app = self._app
        if rec is None or rec.oid is None or app is None:
            return
        select = getattr(app, "select_table_oids", None)
        if callable(select):
            select([int(rec.oid)], extra_status=TOOL_PREDICT_SOM)

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = int(self._struct_label.width())
        lh = int(self._struct_label.height())
        if lw < 32 or lh < 32:
            lw = browser_structure_preview_width()
            lh = BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT
        return max(1, int(lw * dpr)), max(1, int(lh * dpr)), dpr

    def _fit_preview_pixmap(self, pm: QPixmap, dpr: float) -> QPixmap:
        """Place the map on a white canvas that exactly matches the depiction label."""
        lw = int(self._struct_label.width())
        lh = int(self._struct_label.height())
        if lw < 32 or lh < 32:
            pm.setDevicePixelRatio(dpr)
            return pm
        canvas_w = max(1, int(lw * dpr))
        canvas_h = max(1, int(lh * dpr))
        canvas = QPixmap(canvas_w, canvas_h)
        canvas.fill(QColor(255, 255, 255))
        fitted = pm
        if fitted.width() != canvas_w or fitted.height() != canvas_h:
            fitted = pm.scaled(canvas_w, canvas_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(canvas)
        x = (canvas_w - fitted.width()) // 2
        y = (canvas_h - fitted.height()) // 2
        painter.drawPixmap(x, y, fitted)
        painter.end()
        canvas.setDevicePixelRatio(dpr)
        return canvas

    def _refresh_preview(self) -> None:
        rec = self._current()
        if rec is None:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("")
            return
        if rec.error and not rec.atoms:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText(rec.error)
            return
        pw, ph, dpr = self._preview_pixel_size()
        cache_key = (rec.oid, rec.smiles, pw, ph, len(rec.atoms), self._emphasized_atom)
        pm = self._preview_cache.get(cache_key)
        if pm is None or pm.isNull():
            png = render_som_map_png(
                rec.smiles,
                rec.atoms,
                width=pw,
                height=ph,
                emphasize_atom=self._emphasized_atom,
            )
            if png:
                pm = QPixmap.fromImage(QImage.fromData(png))
                if not pm.isNull():
                    self._preview_cache[cache_key] = pm
        if pm is None or pm.isNull():
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("(could not render SOM map)")
            return
        pm = self._fit_preview_pixmap(pm, dpr)
        self._struct_label.setPixmap(pm)
        self._struct_label.setText("")

    def _selected_atom_id(self) -> int | None:
        model = self._atom_table.selectionModel()
        if model is None:
            return None
        rows = model.selectedRows()
        if not rows:
            return None
        item = self._atom_table.item(rows[0].row(), 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        try:
            return int(data)
        except (TypeError, ValueError):
            return None

    def _on_atom_selection_changed(self) -> None:
        atom_id = self._selected_atom_id()
        if atom_id == self._emphasized_atom:
            return
        self._emphasized_atom = atom_id
        self._refresh_preview()

    def _on_atom_sort_changed(self, logical: int, order) -> None:
        item = self._atom_table.horizontalHeaderItem(int(logical))
        if item is None:
            return
        self._atom_sort_header = item.text()
        self._atom_sort_order = order

    def _fill_atom_table(self, rec: SomBrowseRecord | None) -> None:
        self._atom_table.blockSignals(True)
        hdr = self._atom_table.horizontalHeader()
        hdr.blockSignals(True)
        try:
            self._atom_table.setSortingEnabled(False)
            self._atom_table.clearSelection()
            self._atom_table.setRowCount(0)
            show_phase = rec is not None and _atoms_have_phases(rec.atoms)
            if show_phase:
                labels = ["Atom", "Probability", "SOM", "Phase", "Entropy"]
            else:
                labels = ["Atom", "Probability", "SOM", "Entropy"]
            self._atom_table.setColumnCount(len(labels))
            self._atom_table.setHorizontalHeaderLabels(labels)
            if rec is None or not rec.atoms:
                self._emphasized_atom = None
                return
            ranked = sorted(rec.atoms, key=lambda a: (-a.probability, a.atom_id))
            for hit in ranked:
                r = self._atom_table.rowCount()
                self._atom_table.insertRow(r)
                atom_item = NumericTableWidgetItem()
                atom_item.setData(Qt.EditRole, float(hit.atom_id))
                atom_item.setText(str(hit.atom_id))
                atom_item.setData(Qt.UserRole, int(hit.atom_id))
                self._atom_table.setItem(r, 0, atom_item)

                prob_item = NumericTableWidgetItem()
                prob_item.setData(Qt.EditRole, float(hit.probability))
                prob_item.setText(f"{hit.probability:.3f}")
                self._atom_table.setItem(r, 1, prob_item)

                som_item = QTableWidgetItem("yes" if hit.is_som else "")
                self._atom_table.setItem(r, 2, som_item)

                col = 3
                if show_phase:
                    self._atom_table.setItem(r, col, QTableWidgetItem(som_phase_label(hit)))
                    col += 1
                ent_item = NumericTableWidgetItem()
                if hit.shannon_entropy is None:
                    ent_item.setText("")
                else:
                    ent_item.setData(Qt.EditRole, float(hit.shannon_entropy))
                    ent_item.setText(f"{hit.shannon_entropy:.3f}")
                self._atom_table.setItem(r, col, ent_item)
                if hit.is_som:
                    bg = self.palette().alternateBase()
                    for c in range(self._atom_table.columnCount()):
                        cell = self._atom_table.item(r, c)
                        if cell is not None:
                            cell.setBackground(bg)
            self._emphasized_atom = None
        finally:
            self._atom_table.setSortingEnabled(True)
            sort_name = self._atom_sort_header
            if sort_name and self._atom_table.rowCount() > 0:
                for c in range(self._atom_table.columnCount()):
                    header_item = self._atom_table.horizontalHeaderItem(c)
                    if header_item is not None and header_item.text() == sort_name:
                        self._atom_table.sortItems(c, self._atom_sort_order)
                        break
            elif not sort_name:
                hdr.setSortIndicator(-1, Qt.AscendingOrder)
            hdr.blockSignals(False)
            self._atom_table.blockSignals(False)

    def _update_ui(self) -> None:
        n = len(self._records)
        single = n <= 1
        has_rows = n > 0
        self._btn_first.setEnabled(has_rows)
        self._btn_last.setEnabled(has_rows)
        self._btn_back.setEnabled(not single and has_rows)
        self._btn_fwd.setEnabled(not single and has_rows)
        rec = self._current()
        self._btn_select.setEnabled(rec is not None and rec.oid is not None)
        if not has_rows:
            if self._cb_only_selected.isChecked():
                self._meta.setText(
                    "No selected SOM rows — uncheck “Browse Only Selected” or select rows in the table."
                )
            else:
                self._meta.setText("No SOM results.")
            self._fill_atom_table(None)
            self._refresh_preview()
            return
        self._idx = max(0, min(self._idx, n - 1))
        rec = self._current()
        row_txt = ""
        if rec is not None and rec.oid is not None and self._app is not None:
            try:
                logical = int(self._app._table_model.logical_row_for_oid(int(rec.oid)))
                if logical >= 0:
                    row_txt = f"  ·  Row {logical + 1}"
            except Exception:
                row_txt = ""
        self._meta.setText(f"{TOOL_PREDICT_SOM}: {self._idx + 1} / {n}{row_txt}")
        self._fill_atom_table(rec)
        self._refresh_preview()


class SomBrowserDialog(BrowserHostDialog):
    """Floating window hosting a :class:`SomBrowserWidget`."""

    default_title = f"{TOOL_PREDICT_SOM} Browser"
    panel_cls = SomBrowserWidget
    refresh_preview_on_show = True
    min_size = (560, 640)
    initial_size = (640, 820)

    def set_records(self, records: list[SomBrowseRecord]) -> None:
        panel = getattr(self, "_panel", None)
        if panel is None:
            return
        panel.set_records(records)
