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

"""3Dmol.js view of a docked ligand inside its receptor (results-table side pane)."""

from __future__ import annotations

import base64
import json
import logging
import shutil
from pathlib import Path

from PyQt5.QtCore import QTemporaryDir, QTimer, QUrl, Qt
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from rdkit import Chem

from ..platform_support.qt_webengine_flags import webengine_views_supported
from .mol_viewer_3d import (
    _BUNDLED_3DMOL,
    _RESET_STRUCTURE_JS,
    _reset_structure_menu_html,
    _wire_webengine_console_logger,
    bundled_3dmol_available,
)
from .mol_3d_html import RESIZE_KEEP_VIEW_JS
from .web_resize_scheduler import resize_scheduler_binding_html

logger = logging.getLogger(__name__)

_PDBQT_ELEMENT = {
    "A": "C",
    "C": "C",
    "N": "N",
    "NA": "N",
    "OA": "O",
    "O": "O",
    "S": "S",
    "SA": "S",
    "HD": "H",
    "H": "H",
    "P": "P",
    "F": "F",
    "CL": "Cl",
    "BR": "Br",
    "I": "I",
    "MG": "Mg",
    "MN": "Mn",
    "ZN": "Zn",
    "CA": "Ca",
    "FE": "Fe",
}


def pdbqt_type_to_element(atom_type: str) -> str:
    """Map an AutoDock/PDBQT atom type to a PDB element symbol."""
    raw = (atom_type or "").strip()
    if not raw:
        return "C"
    key = raw.upper()
    if key in _PDBQT_ELEMENT:
        return _PDBQT_ELEMENT[key]
    if key[:2] in _PDBQT_ELEMENT:
        return _PDBQT_ELEMENT[key[:2]]
    if key[:1] in _PDBQT_ELEMENT:
        return _PDBQT_ELEMENT[key[:1]]
    letters = "".join(ch for ch in raw if ch.isalpha())
    if not letters:
        return "C"
    if len(letters) == 1:
        return letters.upper()
    return letters[0].upper() + letters[1].lower()


def pdbqt_to_pdb_text(text: str) -> str:
    """Convert PDBQT ATOM/HETATM records to PDB so 3Dmol can draw cartoons."""
    out: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith(("ATOM", "HETATM")):
            rec = (line[:6] if len(line) >= 6 else line.ljust(6)).ljust(6)
            body = line[6:66] if len(line) >= 66 else line[6:].ljust(60)
            tokens = line.split()
            atype = tokens[-1] if tokens else ""
            elem = pdbqt_type_to_element(atype)
            out.append(f"{rec}{body}          {elem:>2s}")
        elif line.startswith(("TER", "END", "CRYST1", "MODEL", "ENDMDL")):
            out.append(line.rstrip())
    if out and out[-1] != "END":
        out.append("END")
    return "\n".join(out) + ("\n" if out else "")


def load_receptor_display_text(path: str | Path | None) -> str:
    """Read a receptor PDB/PDBQT and return PDB text suitable for 3Dmol."""
    if path is None:
        return ""
    rec = Path(str(path)).expanduser()
    if not rec.is_file():
        return ""
    try:
        raw = rec.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Could not read receptor for dock view: %s", exc)
        return ""
    suffix = rec.suffix.lower()
    if suffix == ".pdbqt" or "ROOT" in raw[:400] or "TORSDOF" in raw[:800]:
        return pdbqt_to_pdb_text(raw)
    if suffix == ".pdb":
        return raw
    return pdbqt_to_pdb_text(raw) or raw


def ligand_display_payload(mol: Chem.Mol | None) -> tuple[str, str]:
    """Return ``(base64, 3Dmol format)`` for a docked pose without re-embedding."""
    if mol is None:
        return "", "sdf"
    try:
        if mol.GetNumAtoms() == 0 or mol.GetNumConformers() < 1:
            return "", "sdf"
    except Exception:
        return "", "sdf"
    try:
        block = Chem.MolToMolBlock(mol)
        if block and block.strip():
            return base64.b64encode(block.encode("utf-8")).decode("ascii"), "sdf"
    except Exception:
        logger.debug("Dock pose MolBlock failed", exc_info=True)
    try:
        block = Chem.MolToPDBBlock(mol)
        if block and block.strip():
            return base64.b64encode(block.encode("utf-8")).decode("ascii"), "pdb"
    except Exception:
        logger.debug("Dock pose PDB block failed", exc_info=True)
    return "", "sdf"


def ligand_mol_to_pdb_text(
    mol: Chem.Mol | None,
    *,
    resn: str = "LIG",
    chain: str = "Z",
) -> str:
    """Write a docked pose as HETATM PDB so Protein Viewer inventories it as a ligand."""
    from ..protein.structure_atoms import _pdb_from_atoms
    from ..protein.structure_component_types import AMINO_ACIDS, NUCLEIC_ACIDS, StructureAtom

    if mol is None:
        return ""
    try:
        if mol.GetNumAtoms() == 0 or mol.GetNumConformers() < 1:
            return ""
        conf = mol.GetConformer()
    except Exception:
        return ""
    default_resn = (resn or "LIG").strip().upper() or "LIG"
    default_chain = ((chain or "Z").strip() or "Z")[:1]
    atoms: list[StructureAtom] = []
    for atom in mol.GetAtoms():
        try:
            pos = conf.GetAtomPosition(atom.GetIdx())
        except Exception:
            continue
        info = atom.GetPDBResidueInfo() if hasattr(atom, "GetPDBResidueInfo") else None
        name = (atom.GetSymbol() or "C").strip() or "C"
        atom_resn = default_resn
        atom_chain = default_chain
        atom_resi = "1"
        icode = ""
        if info is not None:
            raw_name = (info.GetName() or "").strip()
            if raw_name:
                name = raw_name
            raw_resn = (info.GetResidueName() or "").strip().upper()
            if raw_resn and raw_resn not in AMINO_ACIDS and raw_resn not in NUCLEIC_ACIDS:
                atom_resn = raw_resn
            raw_chain = (info.GetChainId() or "").strip()
            if raw_chain:
                atom_chain = raw_chain[:1]
            try:
                atom_resi = str(int(info.GetResidueNumber()))
            except (TypeError, ValueError):
                atom_resi = str(info.GetResidueNumber() or "1")
            icode = (info.GetInsertionCode() or "").strip()
        atoms.append(
            StructureAtom(
                chain=atom_chain,
                resn=atom_resn,
                resi=atom_resi or "1",
                icode=icode,
                name=name,
                elem=(atom.GetSymbol() or "C").upper(),
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                het=True,
            )
        )
    return _pdb_from_atoms(atoms)


def pose_manager_slot_name(mol: Chem.Mol | None, index: int, *, prefix: str = "Pose") -> str:
    """Manager file name for a docked pose (``Pose 3.pdb``)."""
    label = f"{prefix} {max(1, int(index))}"
    if mol is not None:
        for key in ("minimizedAffinity", "CNNaffinity", "CNNscore"):
            try:
                val = (mol.GetProp(key) or "").strip() if mol.HasProp(key) else ""
            except Exception:
                val = ""
            if val:
                label = f"{prefix} {max(1, int(index))} ({val})"
                break
    return f"{label}.pdb"


DEFAULT_RENDER_STYLES = {
    "receptor": "cartoon",
    "ligand": "ballstick",
    "pocket": "stick",
}
RENDER_COMPONENT_LABELS = {
    "receptor": "Receptor",
    "ligand": "Ligand",
    "pocket": "Pocket residues",
}
RENDER_STYLE_CHOICES = {
    "receptor": (
        ("cartoon", "Cartoon"),
        ("surface", "Surface"),
        ("stick", "Sticks"),
        ("line", "Wireframe"),
        ("hidden", "Hidden"),
    ),
    "ligand": (
        ("ballstick", "Ball and stick"),
        ("stick", "Sticks"),
        ("sphere", "Spheres"),
        ("line", "Wireframe"),
        ("hidden", "Hidden"),
    ),
    "pocket": (
        ("ballstick", "Ball and stick"),
        ("stick", "Sticks"),
        ("line", "Wireframe"),
        ("hidden", "Hidden"),
    ),
}


def _viewer_dock_complex_init_script() -> str:
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        __RESET_JS__
        function fitToLigand(v, ligIdx, zoomPad) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          try { v.resize(); } catch (e0) {}
          if (ligIdx >= 0) {
            try { v.zoomTo({model: ligIdx}); } catch (e1) { try { v.zoomTo(); } catch (e2) {} }
          } else {
            try { v.zoomTo(); } catch (e3) {}
          }
          try { v.zoom(zoomPad == null ? 0.72 : zoomPad); } catch (e4) {}
          v.render();
          captureHomeView(v);
        }
        function modelIndices() {
          var recIdx = window.molmanagerRecB64 ? 0 : -1;
          var ligIdx = window.molmanagerLigB64 ? (recIdx >= 0 ? 1 : 0) : -1;
          return {recIdx: recIdx, ligIdx: ligIdx};
        }
        function pocketSelection(recIdx, ligIdx) {
          return {and: [
            {model: recIdx},
            {not: {elem: "H"}},
            {byres: true, within: {distance: 5.0, sel: {model: ligIdx}}}
          ]};
        }
        function clearLabels(v) {
          try { v.removeAllLabels(); } catch (eL) {}
        }
        function addPocketLabels(v, recIdx, ligIdx) {
          if (recIdx < 0 || ligIdx < 0 || typeof v.addResLabels !== "function") return;
          var sel = {and: [
            {model: recIdx},
            {atom: "CA"},
            {byres: true, within: {distance: 5.0, sel: {model: ligIdx}}}
          ]};
          try {
            v.addResLabels(sel, {
              fontSize: 12,
              fontColor: "black",
              showBackground: true,
              backgroundColor: "white",
              backgroundOpacity: 0.88,
              inFront: true
            });
          } catch (eLab) {}
        }
        function keepViewResize(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var saved = null;
          try { saved = v.getView(); } catch (eV) {}
          try { v.resize(); } catch (eR) {}
          if (saved && saved.length && typeof v.setView === "function") {
            try { v.setView(saved); } catch (eSet) {}
          }
          v.render();
        }
        function applyLigandStyle(v, ligIdx, style) {
          if (ligIdx < 0) return;
          var sel = {model: ligIdx};
          if (style === "hidden") v.setStyle(sel, {hidden: true});
          else if (style === "stick") v.setStyle(sel, {stick: {radius: 0.18}});
          else if (style === "sphere") v.setStyle(sel, {sphere: {scale: 0.35}});
          else if (style === "line") v.setStyle(sel, {line: {linewidth: 2}});
          else v.setStyle(sel, {stick: {radius: 0.18}, sphere: {scale: 0.26}});
        }
        function applyReceptorStyle(v, recIdx, ligIdx, styles) {
          if (recIdx < 0) return;
          var recSel = {model: recIdx};
          var recStyle = (styles && styles.receptor) || "cartoon";
          var pocket = (styles && styles.pocket) || "stick";
          try { v.removeAllSurfaces(); } catch (eS) {}
          if (recStyle === "hidden") {
            v.setStyle(recSel, {hidden: true});
          } else if (recStyle === "stick") {
            v.setStyle(recSel, {stick: {radius: 0.12}});
          } else if (recStyle === "line") {
            v.setStyle(recSel, {line: {}});
          } else if (recStyle === "surface") {
            v.setStyle(recSel, {cartoon: {color: "lightgray"}});
            try {
              v.addSurface($3Dmol.SurfaceType.VDW, {opacity: 0.65, color: "white"}, recSel);
            } catch (eSurf) {}
          } else {
            v.setStyle(recSel, {cartoon: {color: "spectrum"}});
          }
          if (ligIdx >= 0 && recStyle !== "hidden" && pocket !== "hidden") {
            var pocketSel = pocketSelection(recIdx, ligIdx);
            try {
              if (pocket === "line") v.addStyle(pocketSel, {line: {}});
              else if (pocket === "ballstick") v.addStyle(pocketSel, {stick: {radius: 0.14}, sphere: {scale: 0.22}});
              else v.addStyle(pocketSel, {stick: {radius: 0.12}});
            } catch (eW) {}
          }
        }
        function applyAllStyles(v, styles) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var idx = modelIndices();
          var st = styles || window.molmanagerRenderStyles || {};
          clearLabels(v);
          applyReceptorStyle(v, idx.recIdx, idx.ligIdx, st);
          applyLigandStyle(v, idx.ligIdx, st.ligand || "ballstick");
          if (st.labels) addPocketLabels(v, idx.recIdx, idx.ligIdx);
        }
        const opts = { backgroundColor: "white" };
        const viewer = $3Dmol.createViewer("v", opts);
        window.molmanagerViewer = viewer;
        window.molmanagerRecB64 = "";
        window.molmanagerRecFmt = "pdb";
        window.molmanagerLigB64 = "";
        window.molmanagerLigFmt = "sdf";
        window.molmanagerRenderStyles = {receptor: "cartoon", ligand: "ballstick", pocket: "stick"};
        installResetStructureMenu();
        window.molmanagerResizeKeepView = function () { keepViewResize(window.molmanagerViewer); };
        window.molmanagerApplyRenderStyles = function (styles) {
          if (!window.molmanagerViewer) return;
          if (styles) window.molmanagerRenderStyles = styles;
          applyAllStyles(window.molmanagerViewer, window.molmanagerRenderStyles);
          keepViewResize(window.molmanagerViewer);
        };
        window.molmanagerApplyPocketView = function () {
          if (!window.molmanagerViewer) return;
          window.molmanagerRenderStyles = {
            receptor: "cartoon",
            ligand: "ballstick",
            pocket: "ballstick",
            labels: true
          };
          var v = window.molmanagerViewer;
          var idx = modelIndices();
          applyAllStyles(v, window.molmanagerRenderStyles);
          fitToLigand(v, idx.ligIdx, 0.85);
        };
        window.molmanagerSetDockComplexPayload = function (payload) {
          if (!window.molmanagerViewer || !payload) return;
          var v = window.molmanagerViewer;
          window.molmanagerRecB64 = payload.rec || "";
          window.molmanagerRecFmt = payload.recFmt || "pdb";
          window.molmanagerLigB64 = payload.lig || "";
          window.molmanagerLigFmt = payload.ligFmt || "sdf";
          if (payload.styles) window.molmanagerRenderStyles = payload.styles;
          var refit = !!payload.refit;
          v.clear();
          try { v.removeAllSurfaces(); } catch (eClr) {}
          var recIdx = -1;
          var ligIdx = -1;
          if (window.molmanagerRecB64) {
            v.addModel(atob(window.molmanagerRecB64), window.molmanagerRecFmt);
            recIdx = 0;
          }
          if (window.molmanagerLigB64) {
            v.addModel(atob(window.molmanagerLigB64), window.molmanagerLigFmt);
            ligIdx = recIdx >= 0 ? 1 : 0;
          }
          applyAllStyles(v, window.molmanagerRenderStyles);
          if (refit) {
            fitToLigand(v, ligIdx);
          } else {
            keepViewResize(v);
          }
        };
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return tmpl.replace("__RESET_JS__", _RESET_STRUCTURE_JS)


def _assemble_dock_complex_page(*, script_src: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#fff;}}</style>
</head>
<body>
  <div id="v"></div>
{resize_scheduler_binding_html(RESIZE_KEEP_VIEW_JS)}
{_reset_structure_menu_html()}
{_viewer_dock_complex_init_script()}
  <script src="{script_src}" onload="molmanagerInitView()"></script>
</body>
</html>"""


def build_dock_complex_html() -> str:
    """Return the dock-complex 3Dmol page (offline bundle when available)."""
    if bundled_3dmol_available():
        return _assemble_dock_complex_page(script_src="3Dmol-min.js")
    return _assemble_dock_complex_page(script_src="https://3dmol.org/build/3Dmol-min.js")


class DockComplexEmbedView(QWidget):
    """Side-pane 3Dmol view: receptor cartoon plus the selected docked pose."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending_payload: dict | None = None
        self._web = None
        self._bootstrapped = False
        self._rec_b64 = ""
        self._rec_fmt = "pdb"
        self._lig_b64 = ""
        self._lig_fmt = "sdf"
        self._fitted = False
        self._styles = dict(DEFAULT_RENDER_STYLES)
        self._pocket_labels = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self.resize_keep_view)
        self._status = QLabel("Docked pose in receptor", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: palette(mid); padding: 8px;")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_web()
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
            logger.debug("Dock complex resize-keep-view failed", exc_info=True)

    def _ensure_web(self) -> None:
        if self._bootstrapped:
            return
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return
        if not webengine_views_supported():
            return
        self._bootstrapped = True
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            _wire_webengine_console_logger(web)
            try:
                s = web.settings()
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            web.loadFinished.connect(self._on_load_finished)
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                index.write_text(build_dock_complex_html(), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                web.setHtml(build_dock_complex_html(), QUrl("https://3dmol.org/"))
            self._web = web
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            logger.warning("Dock complex 3D view unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D view unavailable.\nInstall matching PyQtWebEngine and restart with "
                "`python -m molmanager`."
            )

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_payload is not None:
            payload = self._pending_payload
            self._pending_payload = None
            self._run_payload(payload)
        if self._web_ready:
            self.schedule_resize_keep_view()
            QTimer.singleShot(200, self.resize_keep_view)

    def render_styles(self) -> dict[str, str]:
        return dict(self._styles)

    def _styles_payload(self) -> dict:
        out = dict(self._styles)
        if self._pocket_labels:
            out["labels"] = True
        return out

    def apply_pocket_view(self) -> None:
        """Nearby residues as ball-and-stick with residue labels, zoomed on the ligand."""
        self._styles = {
            "receptor": "cartoon",
            "ligand": "ballstick",
            "pocket": "ballstick",
        }
        self._pocket_labels = True
        if self._pending_payload is not None:
            self._pending_payload["styles"] = self._styles_payload()
            self._pending_payload["refit"] = True
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript(
                "if (window.molmanagerApplyPocketView) window.molmanagerApplyPocketView();"
            )
        except Exception:
            logger.debug("Dock complex pocket view failed", exc_info=True)

    def set_render_style(self, component: str, style: str) -> None:
        """Change how one 3D component is drawn without resetting the camera."""
        allowed = {key for key, _label in RENDER_STYLE_CHOICES.get(component, ())}
        if component not in self._styles or style not in allowed:
            return
        had_labels = self._pocket_labels
        self._pocket_labels = False
        if self._styles.get(component) == style and not had_labels:
            return
        self._styles[component] = style
        payload_styles = self._styles_payload()
        if self._pending_payload is not None:
            self._pending_payload["styles"] = payload_styles
        if self._web is None or not self._web_ready:
            return
        js = (
            "if (window.molmanagerApplyRenderStyles) "
            f"window.molmanagerApplyRenderStyles({json.dumps(payload_styles)});"
        )
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("Dock complex apply styles failed", exc_info=True)

    def _push(self, *, refit: bool) -> None:
        self._run_payload(
            {
                "rec": self._rec_b64,
                "recFmt": self._rec_fmt,
                "lig": self._lig_b64,
                "ligFmt": self._lig_fmt,
                "refit": bool(refit),
                "styles": self._styles_payload(),
            }
        )

    def _run_payload(self, payload: dict) -> None:
        if self._web is None or not self._web_ready:
            self._pending_payload = payload
            return
        js = (
            "if (window.molmanagerSetDockComplexPayload) "
            f"window.molmanagerSetDockComplexPayload({json.dumps(payload)});"
        )
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("Dock complex set payload failed", exc_info=True)

    def set_receptor_path(self, path: str | Path | None) -> None:
        """Load receptor PDB/PDBQT coordinates (cartoon) from disk."""
        text = load_receptor_display_text(path)
        if text:
            self._rec_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            self._rec_fmt = "pdb"
        else:
            self._rec_b64 = ""
            self._rec_fmt = "pdb"
        self._fitted = False
        self._push(refit=True)

    def set_ligand_mol(self, mol: Chem.Mol | None) -> None:
        """Show *mol* using its existing docked coordinates (no ETKDG re-embed)."""
        b64, fmt = ligand_display_payload(mol)
        same = b64 == self._lig_b64 and fmt == self._lig_fmt
        self._lig_b64 = b64
        self._lig_fmt = fmt
        if same and self._fitted:
            return
        refit = not self._fitted
        if b64:
            self._fitted = True
        self._push(refit=refit)
