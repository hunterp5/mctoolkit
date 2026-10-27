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

"""Sketcher / preview 3Dmol.js embed (no atom-info chrome)."""

from __future__ import annotations

import json
import logging
import shutil
from contextlib import suppress
from pathlib import Path

from PyQt5.QtCore import Qt, QTemporaryDir, QTimer, QUrl
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from rdkit import Chem

from ..platform_support.qt_webengine_flags import (
    apply_viewer_webengine_settings,
    refuse_remote_viewer_script,
    webengine_views_supported,
)
from .mol_3d_html import (
    _BUNDLED_3DMOL,
    _cdn_embed_fallback_html,
    _mol_block_b64,
    _offline_embed_index_html,
    _wire_webengine_console_logger,
    bundled_3dmol_available,
)
from .mol_3d_prepare import prepare_mol_2d, prepare_mol_3d

logger = logging.getLogger(__name__)


class Molecule3DEmbedView(QWidget):
    """
    Sketcher side-panel 3Dmol view: no atom-info boxes or mouse-controls overlay.

    Call ``set_molecule`` to refresh after sketch edits (ETKDG embed + MMFF/UFF).
    The WebEngine page is created lazily on first show so QtWebEngine can preload at app start.
    """

    def __init__(self, parent: QWidget | None = None, *, flat: bool = False):
        super().__init__(parent)
        self.setMinimumWidth(420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._flat = bool(flat)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending_b64: str | None = None
        self._web = None
        self._bootstrapped = False
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(50)
        self._refit_timer.timeout.connect(self.refit_view)
        self._status = QLabel("3D preview", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color: palette(mid); padding: 8px;")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_web()
        self.schedule_refit()

    def schedule_refit(self) -> None:
        """Debounced zoom-to-fit after show/load; live resizes are handled in the page."""
        self._refit_timer.start()

    def refit_view(self) -> None:
        """Resize the WebGL canvas and zoom so the whole structure fits with padding."""
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript("if (window.molmanagerRefit) window.molmanagerRefit();")
        except Exception:
            logger.debug("3D embed refit failed", exc_info=True)

    def _ensure_web(self) -> None:
        if self._bootstrapped:
            return
        if not webengine_views_supported():
            return
        self._bootstrapped = True
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            _wire_webengine_console_logger(web)
            with suppress(Exception):
                apply_viewer_webengine_settings(web.settings())
            web.loadFinished.connect(self._on_load_finished)
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                index.write_text(_offline_embed_index_html("", flat=self._flat), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                refuse_remote_viewer_script()
                web.setHtml(
                    _cdn_embed_fallback_html("", flat=self._flat), QUrl("https://3dmol.org/")
                )
            self._web = web
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            logger.warning("Sketcher 3D embed unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D preview unavailable.\nInstall matching PyQtWebEngine and restart with "
                "`python -m molmanager`."
            )

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_b64 is not None:
            b64 = self._pending_b64
            self._pending_b64 = None
            self._run_set_mol_b64(b64)
        if self._web_ready:
            self.schedule_refit()
            QTimer.singleShot(200, self.refit_view)

    def _run_set_mol_b64(self, b64: str) -> None:
        self._ensure_web()
        if self._web is None:
            return
        if not self._web_ready:
            self._pending_b64 = b64
            return
        js = (
            "if (window.molmanagerSetMolB64) window.molmanagerSetMolB64("
            f"{json.dumps(b64)}, {json.dumps(bool(self._flat))});"
        )
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("3D embed set_mol failed", exc_info=True)

    def clear(self) -> None:
        """Clear the displayed model."""
        self._run_set_mol_b64("")

    def set_molecule(self, mol: Chem.Mol | None, *, rebuild_3d: bool = True) -> None:
        """Display *mol*, or clear when *mol* is empty/invalid.

        When ``flat`` is set on this view, a 2D layout is shown in 3Dmol (orthographic).
        Otherwise, when *rebuild_3d* is False and *mol* already has a 3D conformer
        (e.g. a docked ligand), that geometry is kept instead of running ETKDG again.
        """
        if mol is None or mol.GetNumAtoms() == 0:
            self.clear()
            return
        prepared = None
        if self._flat:
            prepared = prepare_mol_2d(mol)
        else:
            if not rebuild_3d:
                try:
                    if mol.GetNumConformers() >= 1 and mol.GetConformer().Is3D():
                        prepared = Chem.Mol(mol)
                except Exception:
                    prepared = None
            if prepared is None:
                prepared = prepare_mol_3d(mol)
        if prepared is None:
            self.clear()
            return
        try:
            self._run_set_mol_b64(_mol_block_b64(prepared))
            self.schedule_refit()
            QTimer.singleShot(150, self.refit_view)
        except Exception:
            logger.debug("3D embed encode failed", exc_info=True)
            self.clear()
