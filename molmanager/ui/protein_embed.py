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


"""WebEngine host for the protein 3Dmol canvas."""

from __future__ import annotations


import json
import logging
import shutil
from pathlib import Path

from PyQt5.QtCore import (
    QEvent,
    QEventLoop,
    QObject,
    QTemporaryDir,
    QTimer,
    QUrl,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..platform_support.qt_webengine_flags import webengine_views_supported
from ..workers.process_pool_utils import application_is_shutting_down
from .mol_3d_html import _BUNDLED_3DMOL, _wire_webengine_console_logger, bundled_3dmol_available
from .protein_viewer_html import build_protein_viewer_html

logger = logging.getLogger(__name__)


class _ProteinViewerBridge(QObject):
    atom_picked = pyqtSignal(str)
    delete_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()

    @pyqtSlot(str)
    def atomPicked(self, payload: str) -> None:
        self.atom_picked.emit(payload)

    @pyqtSlot()
    def deleteRequested(self) -> None:
        self.delete_requested.emit()

    @pyqtSlot()
    def undoRequested(self) -> None:
        self.undo_requested.emit()

    @pyqtSlot()
    def redoRequested(self) -> None:
        self.redo_requested.emit()


class ProteinEmbedView(QWidget):
    """WebEngine host for the protein 3Dmol canvas."""

    atom_picked = pyqtSignal(str)
    delete_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    web_ready = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending_payload: dict | None = None
        self._pending_residue_highlight: list | None = None
        self._pending_pocket: dict | None = None
        self._pending_pocket_surface: dict | None = None
        self._pending_hydrogens: str | None = None
        self._pending_hbonds: dict | None = None
        self._pending_docking_box: dict | None = None
        self._pending_dock_pose: dict | None = None
        self._pending_pharmacophore: dict | None = None
        self._web = None
        self._bootstrapped = False
        self._bridge = _ProteinViewerBridge(self)
        self._bridge.atom_picked.connect(self.atom_picked.emit)
        self._bridge.delete_requested.connect(self.delete_requested.emit)
        self._bridge.undo_requested.connect(self.undo_requested.emit)
        self._bridge.redo_requested.connect(self.redo_requested.emit)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self.resize_keep_view)
        self._status = QLabel("Open a PDB, mmCIF, or other structure file.", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: palette(mid); padding: 16px;")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._bootstrapped:
            QTimer.singleShot(0, self._ensure_web)
        self.schedule_resize_keep_view()

    def schedule_resize_keep_view(self) -> None:
        """Debounced canvas resize after show/load; live resizes are handled in the page."""
        self._resize_timer.start()

    def resize_keep_view(self) -> None:
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript(
                "if (window.molmanagerResizeKeepView) window.molmanagerResizeKeepView();"
            )
        except Exception:
            logger.debug("Protein viewer resize-keep-view failed", exc_info=True)

    def _ensure_web(self) -> None:
        if self._bootstrapped:
            return
        # Shutdown drains the event loop, so a queued show event can land here after the
        # window started closing. Building a WebEngine view at that point crashes Chromium.
        if application_is_shutting_down() or not webengine_views_supported():
            return
        self._bootstrapped = True
        try:
            from PyQt5.QtWebChannel import QWebChannel
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

            web = QWebEngineView(self)
            web.setFocusPolicy(Qt.StrongFocus)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            web.installEventFilter(self)
            _wire_webengine_console_logger(web)
            try:
                s = web.settings()
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            channel = QWebChannel(web.page())
            channel.registerObject("proteinBridge", self._bridge)
            web.page().setWebChannel(channel)
            self._web_channel = channel
            web.loadFinished.connect(self._on_load_finished)
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                index.write_text(build_protein_viewer_html(), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                web.setHtml(build_protein_viewer_html(), QUrl("https://3dmol.org/"))
            self._web = web
            proxy = web.focusProxy()
            if proxy is not None:
                proxy.installEventFilter(self)
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            logger.warning("Protein 3D view unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D view unavailable.\nInstall matching PyQtWebEngine and restart with "
                "`python -m molmanager`."
            )

    def eventFilter(self, obj, event):  # noqa: N802
        """Keep Delete / Undo available when the WebEngine canvas has focus."""
        if event is not None and event.type() == QEvent.KeyPress:
            if self._emit_canvas_edit_key(event):
                return True
        return super().eventFilter(obj, event)

    def _emit_canvas_edit_key(self, event) -> bool:
        key = event.key()
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_requested.emit()
            return True
        try:
            if event.matches(QKeySequence.Undo):
                self.undo_requested.emit()
                return True
            if event.matches(QKeySequence.Redo):
                self.redo_requested.emit()
                return True
        except Exception:
            return False
        return False

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_payload is not None:
            payload = self._pending_payload
            self._pending_payload = None
            self._pending_hydrogens = None
            self._pending_hbonds = None
            if payload.get("dockPose") is not None:
                self._pending_dock_pose = None
            self._run_js("molmanagerSetProteinPayload", payload)
        elif self._web_ready and self._pending_residue_highlight is not None:
            highlight = self._pending_residue_highlight
            self._pending_residue_highlight = None
            self._run_js("molmanagerSetResidueHighlight", highlight)
        if self._web_ready and self._pending_pocket is not None and self._pending_payload is None:
            pocket = self._pending_pocket
            self._pending_pocket = None
            self._run_js("molmanagerSetPocket", pocket)
        if (
            self._web_ready
            and self._pending_pocket_surface is not None
            and self._pending_payload is None
        ):
            surface = self._pending_pocket_surface
            self._pending_pocket_surface = None
            self._run_js("molmanagerSetPocketSurface", surface)
        if self._web_ready and self._pending_hydrogens is not None:
            mode = self._pending_hydrogens
            self._pending_hydrogens = None
            self._run_js("molmanagerSetHydrogens", mode)
        if self._web_ready and self._pending_hbonds is not None and self._pending_payload is None:
            hbonds = self._pending_hbonds
            self._pending_hbonds = None
            self._run_js("molmanagerSetHbonds", hbonds)
        if (
            self._web_ready
            and self._pending_docking_box is not None
            and self._pending_payload is None
        ):
            box = self._pending_docking_box
            self._pending_docking_box = None
            self._run_js("molmanagerSetDockingBox", box)
        if (
            self._web_ready
            and self._pending_dock_pose is not None
            and self._pending_payload is None
        ):
            pose = self._pending_dock_pose
            self._pending_dock_pose = None
            self._run_js("molmanagerSetDockPose", pose)
        if (
            self._web_ready
            and self._pending_pharmacophore is not None
            and self._pending_payload is None
        ):
            pharma = self._pending_pharmacophore
            self._pending_pharmacophore = None
            self._run_js("molmanagerSetPharmacophore", pharma)
        if self._web_ready:
            self.schedule_resize_keep_view()
            QTimer.singleShot(200, self.resize_keep_view)
        self.web_ready.emit()

    def _run_js(self, fn_name: str, payload) -> None:
        if self._web is None or not self._web_ready:
            if fn_name == "molmanagerSetProteinPayload":
                self._pending_payload = payload
            elif fn_name == "molmanagerAddProteinModels":
                if self._pending_payload is None:
                    self._pending_payload = dict(payload)
                    self._pending_payload.setdefault("models", list(payload.get("models") or []))
                else:
                    existing = list(self._pending_payload.get("models") or [])
                    existing.extend(payload.get("models") or [])
                    self._pending_payload["models"] = existing
                    for key in (
                        "components",
                        "residueHighlight",
                        "pocket",
                        "pocketSurface",
                        "hbonds",
                        "dockingBox",
                        "dockPose",
                        "pharmacophore",
                        "hydrogens",
                        "refit",
                    ):
                        if key in payload:
                            self._pending_payload[key] = payload[key]
            elif fn_name == "molmanagerApplyComponentStates" and self._pending_payload is not None:
                self._pending_payload["components"] = payload
            elif fn_name == "molmanagerDeleteComponents" and self._pending_payload is not None:
                drop = set(payload or [])
                self._pending_payload["components"] = [
                    comp
                    for comp in self._pending_payload.get("components") or []
                    if comp.get("id") not in drop
                ]
            elif fn_name == "molmanagerSetResidueHighlight":
                self._pending_residue_highlight = payload
                if self._pending_payload is not None:
                    highlight = payload
                    if isinstance(payload, dict) and "sels" in payload:
                        highlight = payload.get("sels") or []
                    self._pending_payload["residueHighlight"] = highlight
            elif fn_name == "molmanagerSetPocket":
                self._pending_pocket = payload
                if self._pending_payload is not None:
                    pocket = payload
                    if isinstance(payload, dict) and payload.get("_apply") is False:
                        pocket = {k: v for k, v in payload.items() if k != "_apply"}
                    self._pending_payload["pocket"] = pocket
            elif fn_name == "molmanagerSetPocketSurface":
                self._pending_pocket_surface = payload
                if self._pending_payload is not None:
                    self._pending_payload["pocketSurface"] = payload
            elif fn_name == "molmanagerSetHydrogens":
                self._pending_hydrogens = payload
                if self._pending_payload is not None:
                    mode = payload.get("mode") if isinstance(payload, dict) else payload
                    self._pending_payload["hydrogens"] = mode
            elif fn_name == "molmanagerSetHbonds":
                self._pending_hbonds = payload
                if self._pending_payload is not None:
                    self._pending_payload["hbonds"] = payload
            elif fn_name == "molmanagerSetDockingBox":
                self._pending_docking_box = payload
                if self._pending_payload is not None:
                    self._pending_payload["dockingBox"] = payload
            elif fn_name == "molmanagerSetDockPose":
                self._pending_dock_pose = payload
                if self._pending_payload is not None:
                    self._pending_payload["dockPose"] = payload
            elif fn_name == "molmanagerSetPharmacophore":
                self._pending_pharmacophore = payload
                if self._pending_payload is not None:
                    self._pending_payload["pharmacophore"] = payload
            elif fn_name == "molmanagerSetView" and self._pending_payload is not None:
                self._pending_payload["camera"] = payload
            return
        js = f"if (window.{fn_name}) window.{fn_name}({json.dumps(payload)});"
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("Protein viewer %s failed", fn_name, exc_info=True)

    def set_payload(self, payload: dict) -> None:
        self._run_js("molmanagerSetProteinPayload", payload)

    def add_models(self, payload: dict) -> None:
        """Add models to the current canvas without re-parsing already loaded files."""
        self._run_js("molmanagerAddProteinModels", payload)

    def apply_component_states(self, components: list[dict]) -> None:
        self._run_js("molmanagerApplyComponentStates", components)

    def delete_components(self, ids: list[str]) -> None:
        self._run_js("molmanagerDeleteComponents", ids)

    def zoom_to_components(self, ids: list[str]) -> None:
        self._run_js("molmanagerZoomToComponents", ids)

    def set_residue_highlight(self, selections: list[dict]) -> None:
        self._run_js("molmanagerSetResidueHighlight", selections)

    def mutate_residues(self, items: list[dict]) -> None:
        self._run_js("molmanagerMutateResidues", items)

    def delete_residues(self, selections: list[dict]) -> None:
        self._run_js("molmanagerDeleteResidues", selections)

    def edit_bond(self, payload: dict) -> None:
        self._run_js("molmanagerEditBond", payload)

    def zoom_to_selections(self, selections: list[dict]) -> None:
        self._run_js("molmanagerZoomToSelections", selections)

    def set_pocket(self, pocket: dict | None) -> None:
        self._run_js("molmanagerSetPocket", pocket)

    def set_pocket_surface(self, surface: dict | None) -> None:
        self._run_js("molmanagerSetPocketSurface", surface or {"active": False})

    def set_hydrogens(self, mode: str) -> None:
        chosen = mode if mode in ("all", "polar", "none") else "polar"
        self._run_js("molmanagerSetHydrogens", chosen)

    def set_hbonds(self, spec: dict | None) -> None:
        self._run_js("molmanagerSetHbonds", spec or {"active": False, "bonds": []})

    def set_docking_box(self, box: dict | None) -> None:
        self._run_js("molmanagerSetDockingBox", box or {"active": False})

    def set_dock_pose(self, pose: dict | None) -> None:
        self._run_js("molmanagerSetDockPose", pose or {"active": False})

    def set_pharmacophore(self, spec: dict | None) -> None:
        self._run_js("molmanagerSetPharmacophore", spec or {"active": False})

    def set_camera(self, view) -> None:
        if view is None:
            return
        self._run_js("molmanagerSetView", view)

    def fetch_camera(self, timeout_ms: int = 250):
        """Return 3Dmol getView() or None if the canvas is not ready."""
        if self._web is None or not self._web_ready:
            pending = getattr(self, "_pending_payload", None) or {}
            camera = pending.get("camera") if isinstance(pending, dict) else None
            return camera
        loop = QEventLoop()
        box: dict = {"value": None, "done": False}

        def _cb(val) -> None:
            box["value"] = val
            box["done"] = True
            loop.quit()

        try:
            self._web.page().runJavaScript(
                "window.molmanagerGetView ? window.molmanagerGetView() : null",
                _cb,
            )
        except Exception:
            logger.debug("Protein viewer getView failed", exc_info=True)
            return None
        QTimer.singleShot(max(1, int(timeout_ms)), loop.quit)
        loop.exec_()
        return box["value"] if box["done"] else None
