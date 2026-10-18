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

"""3Dmol.js HTML/JS page assembly for ligand viewers."""

from __future__ import annotations

import base64
import colorsys
import json
import logging
from pathlib import Path

from rdkit import Chem

from ..platform_support.qt_webengine_flags import webengine_views_supported
from .web_resize_scheduler import resize_scheduler_binding_html

logger = logging.getLogger(__name__)

_BUNDLED_3DMOL = Path(__file__).resolve().parent / "static" / "3Dmol-min.js"

#: Resize the WebGL canvas and keep the current camera.
RESIZE_KEEP_ZOOM_JS = "if (window.molmanagerRefit) window.molmanagerRefit({zoom: false});"
#: Resize and zoom-to-fit (sketcher side panel keeps the whole structure framed).
RESIZE_REFIT_JS = "if (window.molmanagerRefit) window.molmanagerRefit();"
#: Resize the canvas while keeping the camera (protein / dock-complex viewers).
RESIZE_KEEP_VIEW_JS = "if (window.molmanagerResizeKeepView) window.molmanagerResizeKeepView();"

# Stick colors for superposed conformers. Overlay slots use unique entries (no wrap).
_SUPERPOSE_PALETTE = (
    "#c0392b",
    "#2980b9",
    "#27ae60",
    "#8e44ad",
    "#f39c12",
    "#16a085",
    "#d35400",
    "#34495e",
    "#e91e63",
    "#3f51b5",
    "#009688",
    "#cddc39",
    "#795548",
    "#00bcd4",
    "#ff5722",
    "#607d8b",
    "#9c27b0",
    "#2196f3",
    "#4caf50",
    "#ffc107",
    "#673ab7",
    "#03a9f4",
    "#8bc34a",
    "#ff9800",
    "#f44336",
    "#3d5afe",
    "#1de9b6",
    "#c6ff00",
    "#a1887f",
    "#18ffff",
    "#ff6e40",
    "#90a4ae",
)


def _hsv_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(float(h) % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def distinct_superpose_colors(n: int) -> list[str]:
    """Return *n* unique hex colors for one superpose overlay (legend and sticks)."""
    want = max(0, int(n))
    if want == 0:
        return []
    if want <= len(_SUPERPOSE_PALETTE):
        return list(_SUPERPOSE_PALETTE[:want])
    out = list(_SUPERPOSE_PALETTE)
    used = {c.lower() for c in out}
    k = 0
    while len(out) < want and k < want * 80:
        hue = (k * 0.618033988749895) % 1.0
        sat = 0.55 + 0.35 * ((k % 5) / 4.0)
        val = 0.55 + 0.35 * (((k // 3) % 5) / 4.0)
        color = _hsv_hex(hue, sat, val)
        k += 1
        if color.lower() in used:
            continue
        used.add(color.lower())
        out.append(color)
    j = 0
    while len(out) < want:
        color = f"#{(37 * j) % 200 + 40:02x}{(91 * j) % 200 + 40:02x}{(17 * j) % 200 + 40:02x}"
        j += 1
        if color.lower() in used:
            continue
        used.add(color.lower())
        out.append(color)
    return out


def superpose_color_for_conf(conf_idx: int) -> str:
    """Unique overlay color for slot *conf_idx* in a growing unique series."""
    i = max(0, int(conf_idx))
    return distinct_superpose_colors(i + 1)[i]


def conf_legend_entries(conf_indices: list[int]) -> list[dict[str, str]]:
    """Legend rows: 1-based Conf id matching the strain table, plus unique stick color."""
    idxs = [int(idx) for idx in conf_indices]
    colors = distinct_superpose_colors(len(idxs))
    return [{"id": str(idx + 1), "color": colors[i]} for i, idx in enumerate(idxs)]


def bundled_3dmol_available() -> bool:
    """True if the vendored 3Dmol script is present (offline-capable viewer)."""
    try:
        return _BUNDLED_3DMOL.is_file() and _BUNDLED_3DMOL.stat().st_size > 10_000
    except OSError:
        return False


def _js_console_is_benign(msg: str) -> bool:
    """True for Chromium/3Dmol noise that should not hit the user console."""
    low = msg.lower()
    if "violation" in low and "non-passive" in low:
        return True
    if "deprecated" in low or "deprecation" in low:
        return True
    if "shared image" in low or "sharedimage" in low:
        return True
    if "invalid mailbox" in low or "non-existent mailbox" in low:
        return True
    if "gl_invalid_operation" in low or "gles2_cmd_decoder" in low:
        return True
    if "webgl" in low:
        return True
    return False


def _log_webengine_js_console(level, message, line, source) -> None:
    """Route JS console lines to Python logging; keep GPU/3Dmol chatter at DEBUG."""
    msg = (message or "").strip()
    if not msg:
        return
    if _js_console_is_benign(msg):
        logger.debug("3D viewer (benign): %s", msg)
        return
    try:
        from PyQt5.QtWebEngineWidgets import QWebEnginePage
    except Exception:
        logger.debug("3D viewer JS: %s", msg)
        return
    if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
        logger.warning("3D viewer JS error: %s (line %s, %s)", msg, line, source)
    elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
        logger.debug("3D viewer JS warning: %s", msg)
    else:
        logger.debug("3D viewer JS: %s", msg)


def _wire_webengine_console_logger(web) -> None:
    """
    Capture Qt WebEngine JavaScript console output without dumping it to stderr.

    Qt's default ``QWebEnginePage.javaScriptConsoleMessage`` prints every JS
    console line via ``qWarning``. A custom page swallows that and logs through
    Python instead. GPU SharedImage spam from Chromium itself is suppressed by
    ``configure_qtwebengine_quiet_logs`` before WebEngine starts.
    """
    try:
        # Constructing a page subclass aborts the process on platform plugins without a
        # windowing surface (QT_QPA_PLATFORM=offscreen), so leave Qt's default page there.
        if not webengine_views_supported():
            return
        from PyQt5.QtWebEngineWidgets import QWebEnginePage

        cls = getattr(_wire_webengine_console_logger, "_page_cls", None)
        if cls is None:

            class QuietWebEnginePage(QWebEnginePage):
                def javaScriptConsoleMessage(self, level, message, line_number, source_id):
                    _log_webengine_js_console(level, message, line_number, source_id)

            cls = QuietWebEnginePage
            _wire_webengine_console_logger._page_cls = cls
        web.setPage(cls(web))
    except Exception:
        logger.debug("3D viewer: could not attach JS console logger", exc_info=True)


def _reset_structure_menu_html() -> str:
    """Right-click menu to restore the originally fitted camera."""
    return """
<style>
  #chem-reset-menu {
    display: none;
    position: fixed;
    z-index: 60;
    min-width: 168px;
    background: #fff;
    border: 1px solid #c8c8c8;
    border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0,0,0,.16);
    padding: 4px;
    font: 13px/1.3 system-ui, Segoe UI, sans-serif;
  }
  #chem-reset-menu button {
    display: block;
    width: 100%;
    text-align: left;
    border: 0;
    background: transparent;
    padding: 6px 10px;
    border-radius: 4px;
    cursor: pointer;
    color: #111;
  }
  #chem-reset-menu button:hover { background: #e8eef5; }
</style>
<div id="chem-reset-menu" role="menu">
  <button type="button" id="chem-reset-structure" role="menuitem">Reset Structure</button>
</div>
"""


_RESET_STRUCTURE_JS = r"""
        function captureHomeView(v) {
          v = v || window.molmanagerViewer;
          if (!v || typeof v.getView !== "function") return;
          try {
            var home = v.getView();
            if (home && home.length) window.molmanagerHomeView = home.slice();
          } catch (eH) {}
        }
        function applyHomeView(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          try { v.resize(); } catch (e0) {}
          var home = window.molmanagerHomeView;
          if (home && home.length && typeof v.setView === "function") {
            try { v.setView(home); v.render(); return; } catch (e1) {}
          }
          try { v.zoomTo(); } catch (e2) {}
          try { v.zoom(0.88); } catch (e3) {}
          v.render();
        }
        function fitAndCapture(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          try { v.resize(); } catch (e0) {}
          try { v.zoomTo(); } catch (e1) {}
          try { v.zoom(0.88); } catch (e2) {}
          v.render();
          captureHomeView(v);
        }
        function hideResetMenu() {
          var el = document.getElementById("chem-reset-menu");
          if (el) el.style.display = "none";
        }
        function showResetMenu(clientX, clientY) {
          var el = document.getElementById("chem-reset-menu");
          if (!el) return;
          el.style.display = "block";
          var w = el.offsetWidth || 168;
          var h = el.offsetHeight || 36;
          var x = Math.max(4, Math.min(clientX, window.innerWidth - w - 4));
          var y = Math.max(4, Math.min(clientY, window.innerHeight - h - 4));
          el.style.left = x + "px";
          el.style.top = y + "px";
        }
        function installResetStructureMenu() {
          var host = document.getElementById("v") || document.body;
          var downX = 0, downY = 0;
          host.addEventListener("mousedown", function (e) {
            if (e.button === 2) { downX = e.clientX; downY = e.clientY; }
          });
          host.addEventListener("contextmenu", function (e) {
            e.preventDefault();
            if (Math.abs(e.clientX - downX) > 5 || Math.abs(e.clientY - downY) > 5) return;
            showResetMenu(e.clientX, e.clientY);
          });
          var btn = document.getElementById("chem-reset-structure");
          if (btn) {
            btn.addEventListener("click", function (e) {
              e.preventDefault();
              e.stopPropagation();
              hideResetMenu();
              applyHomeView();
            });
          }
          document.addEventListener("click", function (e) {
            var el = document.getElementById("chem-reset-menu");
            if (!el || el.style.display === "none") return;
            if (el.contains(e.target)) return;
            hideResetMenu();
          });
          document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") hideResetMenu();
          });
          window.molmanagerResetStructure = function () { hideResetMenu(); applyHomeView(); };
        }
"""


def _atom_info_panel_html() -> str:
    """Fixed panel for hover preview and click-selected atom details (3Dmol click/hover callbacks)."""
    return """
<div id="chem-atom-panel" style="position:fixed;top:8px;left:8px;z-index:21;max-width:min(340px,calc(100vw - 16px));font:12px/1.4 system-ui,Segoe UI,sans-serif;background:rgba(255,255,255,0.95);border:1px solid #c8c8c8;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.12);padding:8px 10px;pointer-events:none;">
  <div style="font-weight:600;margin-bottom:4px;">Atom</div>
  <div id="chem-atom-hover" style="font-size:11px;color:#555;min-height:1.2em;"></div>
  <div id="chem-atom-detail" style="margin-top:6px;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;font-size:11px;color:#111;"></div>
</div>
"""


def _viewer_init_script_fragment(mol_b64: str, *, flat: bool) -> str:
    """JavaScript to create a 3Dmol viewer (no atom-info panel / mouse-help overlay)."""
    flat_js = "true" if flat else "false"
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        const data = atob("__MOLB64__");
        const flat = __FLAT__;
        const opts = flat ? { backgroundColor: "white", orthographic: true } : { backgroundColor: "white" };
        const viewer = $3Dmol.createViewer("v", opts);
        window.molmanagerViewer = viewer;
        __RESET_JS__
        installResetStructureMenu();
        viewer.addModel(data, "mol");
        var stickR = flat ? 0.1 : 0.12;
        var sph = flat ? 0.18 : 0.22;
        viewer.setStyle({}, { stick: { radius: stickR }, sphere: { scale: sph } });
        fitAndCapture(viewer);
        window.molmanagerRefit = function (opts) {
          if (!window.molmanagerViewer) return;
          if (opts && opts.zoom) fitAndCapture(window.molmanagerViewer);
          else {
            try { window.molmanagerViewer.resize(); } catch (e0) {}
            window.molmanagerViewer.render();
          }
        };
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return (
        tmpl.replace("__MOLB64__", mol_b64)
        .replace("__FLAT__", flat_js)
        .replace("__RESET_JS__", _RESET_STRUCTURE_JS)
    )


def _viewer_embed_init_script_fragment(mol_b64: str = "", *, flat: bool = False) -> str:
    """Minimal 3Dmol init for sketcher side panel: no atom pick UI; live ``molmanagerSetMolB64``."""
    flat_js = "true" if flat else "false"
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        __RESET_JS__
        window.molmanagerFlat = __FLAT__;
        const opts = window.molmanagerFlat
          ? { backgroundColor: "white", orthographic: true }
          : { backgroundColor: "white" };
        const viewer = $3Dmol.createViewer("v", opts);
        window.molmanagerViewer = viewer;
        installResetStructureMenu();
        window.molmanagerRefit = function () { fitAndCapture(window.molmanagerViewer); };
        window.molmanagerSetMolB64 = function (b64, flat) {
          if (typeof flat !== "undefined") window.molmanagerFlat = !!flat;
          if (!window.molmanagerViewer) return;
          var v = window.molmanagerViewer;
          var isFlat = !!window.molmanagerFlat;
          v.clear();
          if (b64) {
            v.addModel(atob(b64), "mol");
            var stickR = isFlat ? 0.1 : 0.12;
            var sph = isFlat ? 0.18 : 0.22;
            v.setStyle({}, { stick: { radius: stickR }, sphere: { scale: sph } });
            fitAndCapture(v);
          } else {
            v.render();
          }
        };
        window.molmanagerSetMolB64("__MOLB64__");
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return (
        tmpl.replace("__MOLB64__", mol_b64 or "")
        .replace("__RESET_JS__", _RESET_STRUCTURE_JS)
        .replace("__FLAT__", flat_js)
    )


def assemble_3dmol_shell_page(
    *,
    script_src: str,
    init_html: str,
    extra_scripts: str = "",
    background: str = "",
    resize_js: str = "",
) -> str:
    """Minimal 3Dmol host page: canvas, reset menu, init HTML, then the library script.

    ``resize_js`` runs through the shared resize scheduler whenever ``#v`` changes size.
    """
    bg = f"background:{background};" if background else ""
    reset_menu = _reset_structure_menu_html()
    extra = extra_scripts.rstrip() + "\n" if extra_scripts else ""
    resize = resize_scheduler_binding_html(resize_js) if resize_js else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;{bg}}}</style>
</head>
<body>
  <div id="v"></div>
{resize}
{reset_menu}
{init_html}
{extra}  <script src="{script_src}" onload="molmanagerInitView()"></script>
</body>
</html>"""


def _assemble_viewer_page(
    mol_b64: str,
    *,
    flat: bool,
    script_src: str,
    show_atom_panel: bool = False,
    show_mouse_help: bool = False,
) -> str:
    init = _viewer_init_script_fragment(mol_b64, flat=flat)
    help_html = _viewer_help_overlay_html() if show_mouse_help else ""
    atom_panel = _atom_info_panel_html() if show_atom_panel else ""
    reset_menu = _reset_structure_menu_html()
    resize = resize_scheduler_binding_html(RESIZE_KEEP_ZOOM_JS)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}}</style>
</head>
<body>
  <div id="v"></div>
{resize}
{atom_panel}
{reset_menu}
{init}
  <script src="{script_src}" onload="molmanagerInitView()"></script>
{help_html}
</body>
</html>"""


def _assemble_embed_viewer_page(mol_b64: str, *, script_src: str, flat: bool = False) -> str:
    """Sketcher-embedded page: no atom boxes or mouse-controls overlay."""
    init = _viewer_embed_init_script_fragment(mol_b64, flat=flat)
    reset_menu = _reset_structure_menu_html()
    resize = resize_scheduler_binding_html(RESIZE_REFIT_JS)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#fff;}}</style>
</head>
<body>
  <div id="v"></div>
{resize}
{reset_menu}
{init}
  <script src="{script_src}" onload="molmanagerInitView()"></script>
</body>
</html>"""


def _offline_index_html(mol_b64: str, *, flat: bool = False) -> str:
    """Minimal page next to ``3Dmol-min.js`` (same directory)."""
    return _assemble_viewer_page(mol_b64, flat=flat, script_src="3Dmol-min.js")


def _offline_embed_index_html(mol_b64: str = "", *, flat: bool = False) -> str:
    return _assemble_embed_viewer_page(mol_b64, script_src="3Dmol-min.js", flat=flat)


def _offline_index_html_multiconf(
    blocks_json_b64: str,
    *,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    return _assemble_viewer_page_multiconf(
        blocks_json_b64,
        script_src="3Dmol-min.js",
        initial_superpose=initial_superpose,
        initial_conf_index=initial_conf_index,
    )


def _cdn_fallback_html(mol_b64: str, *, flat: bool = False) -> str:
    """Same as offline page but loads 3Dmol from the network (only if the bundle is missing)."""
    return _assemble_viewer_page(
        mol_b64, flat=flat, script_src="https://3dmol.org/build/3Dmol-min.js"
    )


def _cdn_embed_fallback_html(mol_b64: str = "", *, flat: bool = False) -> str:
    return _assemble_embed_viewer_page(
        mol_b64, script_src="https://3dmol.org/build/3Dmol-min.js", flat=flat
    )


def _cdn_fallback_html_multiconf(
    blocks_json_b64: str,
    *,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    return _assemble_viewer_page_multiconf(
        blocks_json_b64,
        script_src="https://3dmol.org/build/3Dmol-min.js",
        initial_superpose=initial_superpose,
        initial_conf_index=initial_conf_index,
    )


def _viewer_help_overlay_html() -> str:
    """On-page reference for 3Dmol.js default GLViewer mouse bindings (matches bundled 3Dmol)."""
    return """
<details id="chem3d-help" style="position:fixed;bottom:6px;right:6px;z-index:20;max-width:min(380px,calc(100vw - 12px));font:12px/1.45 system-ui,Segoe UI,sans-serif;background:rgba(255,255,255,0.94);border:1px solid #c8c8c8;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.12);padding:0;">
  <summary style="cursor:pointer;list-style:none;padding:8px 12px;font-weight:600;user-select:none;">Mouse controls</summary>
  <div style="padding:0 12px 10px 12px;border-top:1px solid #e0e0e0;">
    <ul style="margin:0;padding-left:1.1em;">
      <li><b>Click</b> an atom — select &amp; show details (top-left)</li>
      <li><b>Click</b> empty background — clear selection</li>
      <li><b>Hover</b> an atom — quick label under “Atom”</li>
      <li><b>Left drag</b> — rotate the model</li>
      <li><b>Scroll wheel</b> — zoom in / out</li>
      <li><b>Ctrl + wheel</b> — zoom (reversed direction)</li>
      <li><b>Shift + left drag</b> — zoom (vertical drag)</li>
      <li><b>Middle drag</b> — pan (translate)</li>
      <li><b>Ctrl + left drag</b> — pan (translate)</li>
      <li><b>Right drag</b> — zoom (vertical drag)</li>
      <li><b>Ctrl + right drag</b> — adjust front/back clipping (slab)</li>
    </ul>
  </div>
</details>
<style>
#chem3d-help summary::-webkit-details-marker { display: none; }
#chem3d-help[open] summary { border-bottom: 1px solid #e0e0e0; }
</style>
"""


def build_3dmol_html(mol_b64: str) -> str:
    """Return a self-contained HTML document (offline bundle when available, else CDN)."""
    return (
        _offline_index_html(mol_b64, flat=False)
        if bundled_3dmol_available()
        else _cdn_fallback_html(mol_b64, flat=False)
    )


def _mol_block_b64(mol: Chem.Mol) -> str:
    block = Chem.MolToMolBlock(mol)
    return base64.b64encode(block.encode("utf-8")).decode("ascii")


def _viewer_init_script_multiconf(
    blocks_json_b64: str,
    *,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    """Multi-conformer 3Dmol page: one-at-a-time vs superpose-all (no on-canvas chrome)."""
    init_sp = "true" if initial_superpose else "false"
    start_idx = max(0, int(initial_conf_index))
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        var initialSuperpose = __INIT_SP__;
        var startIdx = __START_IDX__;
        const blocks = JSON.parse(atob("__BLOCKSJSONB64__"));
        if (!blocks || blocks.length === 0) {
          document.body.innerHTML = "<pre style='padding:12px'>No conformers to display.</pre>";
          return;
        }
        if (blocks.length < 2) initialSuperpose = false;
        startIdx = Math.max(0, Math.min(startIdx, blocks.length - 1));
        var viewer = null;
        var curIdx = startIdx;
        var superposed = false;
        var palette = __PALETTE__;
        __RESET_JS__
        installResetStructureMenu();

        function viewerEl() { return document.getElementById("v"); }
        function viewerReadySize() {
          var el = viewerEl();
          return !!(el && el.clientWidth >= 32 && el.clientHeight >= 32);
        }
        function ensureViewer() {
          if (viewer) return viewer;
          viewer = $3Dmol.createViewer("v", { backgroundColor: "white" });
          window.molmanagerViewer = viewer;
          return viewer;
        }

        function applySingleStyle() {
          viewer.setStyle({}, { stick: { radius: 0.12 }, sphere: { scale: 0.22 } });
        }

        function restyleSuperpose(list, colors) {
          var cols = (colors && colors.length) ? colors : distinctOverlayColors(list.length);
          for (var mi = 0; mi < list.length; mi++) {
            var c = cols[mi] || "#888888";
            viewer.setStyle({ model: mi }, { stick: { radius: 0.09, color: c } });
          }
        }

        function hex2(n) {
          var s = Math.max(0, Math.min(255, Math.round(n))).toString(16);
          return s.length < 2 ? "0" + s : s;
        }
        function hsvHex(h, s, v) {
          var i = Math.floor(h * 6);
          var f = h * 6 - i;
          var p = v * (1 - s);
          var q = v * (1 - f * s);
          var t = v * (1 - (1 - f) * s);
          var r, g, b;
          switch (i % 6) {
            case 0: r = v; g = t; b = p; break;
            case 1: r = q; g = v; b = p; break;
            case 2: r = p; g = v; b = t; break;
            case 3: r = p; g = q; b = v; break;
            case 4: r = t; g = p; b = v; break;
            default: r = v; g = p; b = q;
          }
          return "#" + hex2(r * 255) + hex2(g * 255) + hex2(b * 255);
        }
        function distinctOverlayColors(n) {
          n = n | 0;
          if (n <= 0) return [];
          if (n <= palette.length) return palette.slice(0, n);
          var out = palette.slice();
          var used = {};
          for (var u = 0; u < out.length; u++) used[out[u].toLowerCase()] = true;
          var k = 0;
          while (out.length < n && k < n * 80) {
            var h = (k * 0.618033988749895) % 1.0;
            var sat = 0.55 + 0.35 * ((k % 5) / 4.0);
            var val = 0.55 + 0.35 * ((Math.floor(k / 3) % 5) / 4.0);
            var c = hsvHex(h, sat, val);
            k += 1;
            if (used[c.toLowerCase()]) continue;
            used[c.toLowerCase()] = true;
            out.push(c);
          }
          return out;
        }

        function setConfLegend(entries) {
          var el = document.getElementById("chem-conf-legend");
          if (!el) return;
          if (!entries || !entries.length) {
            el.style.display = "none";
            el.innerHTML = "";
            return;
          }
          var parts = ['<div style="font-weight:600;margin-bottom:6px;">Conformers</div>'];
          for (var i = 0; i < entries.length; i++) {
            var id = String(entries[i].id);
            var color = String(entries[i].color || "#888");
            parts.push(
              '<div style="display:flex;align-items:center;gap:8px;margin:3px 0;">'
              + '<span style="flex:0 0 12px;width:12px;height:12px;border-radius:2px;background:'
              + color + ';border:1px solid rgba(0,0,0,.25);"></span>'
              + '<span>Conf ' + id + '</span></div>'
            );
          }
          el.innerHTML = parts.join("");
          el.style.display = "block";
        }

        function allIdxs() {
          var list = [];
          for (var i = 0; i < blocks.length; i++) list.push(i);
          return list;
        }

        function normalizeIdxs(idxs) {
          if (idxs === null || typeof idxs === "undefined") return allIdxs();
          var list = [];
          if (!idxs || !idxs.length) return list;
          for (var k = 0; k < idxs.length; k++) {
            var v = parseInt(idxs[k], 10);
            if (!isFinite(v)) continue;
            v = Math.max(0, Math.min(v, blocks.length - 1));
            if (list.indexOf(v) < 0) list.push(v);
          }
          return list;
        }

        var superposeGen = 0;
        function showSuperpose(idxs, opts) {
          var gen = ++superposeGen;
          var list = normalizeIdxs(idxs);
          var doZoom = !!(opts && opts.zoom);
          if (list.length === 0) {
            superposed = false;
            setConfLegend(null);
            if (viewer) {
              viewer.clear();
              viewer.render();
            }
            return;
          }
          if (list.length === 1) {
            loadConf(list[0]);
            return;
          }
          superposed = true;
          ensureViewer();
          viewer.clear();
          for (var i = 0; i < list.length; i++) {
            if (gen !== superposeGen) return;
            viewer.addModel(atob(blocks[list[i]]), "mol");
          }
          if (gen !== superposeGen) return;
          restyleSuperpose(list, opts && opts.colors);
          if (doZoom) fitAndCapture(viewer);
          else {
            try { viewer.resize(); } catch (e0) {}
            viewer.render();
          }
        }

        function loadConf(i) {
          superposeGen += 1;
          superposed = false;
          setConfLegend(null);
          i = Math.max(0, Math.min(i, blocks.length - 1));
          curIdx = i;
          ensureViewer();
          viewer.clear();
          viewer.addModel(atob(blocks[i]), "mol");
          applySingleStyle();
          fitAndCapture(viewer);
        }

        window.molmanagerRefit = function (opts) {
          if (!viewerReadySize()) return;
          ensureViewer();
          if (opts && opts.zoom) fitAndCapture(viewer);
          else {
            try { viewer.resize(); } catch (e0) {}
            viewer.render();
          }
        };

        function bootView() {
          if (!viewerReadySize()) {
            requestAnimationFrame(bootView);
            return;
          }
          if (initialSuperpose) showSuperpose(null, {zoom: true});
          else loadConf(startIdx);
        }

        window.molmanagerLoadConf = function (i) { loadConf(i); };
        window.molmanagerShowSuperpose = function (idxs, opts) { showSuperpose(idxs, opts); };
        window.molmanagerSetConfLegend = setConfLegend;
        window.molmanagerConfState = function () {
          return { idx: curIdx, superposed: !!superposed, n: blocks.length };
        };
        bootView();
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return (
        tmpl.replace("__BLOCKSJSONB64__", blocks_json_b64)
        .replace("__INIT_SP__", init_sp)
        .replace("__START_IDX__", str(start_idx))
        .replace("__PALETTE__", json.dumps(list(_SUPERPOSE_PALETTE)))
        .replace("__RESET_JS__", _RESET_STRUCTURE_JS)
    )


def _assemble_viewer_page_multiconf(
    blocks_json_b64: str,
    *,
    script_src: str,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    init = _viewer_init_script_multiconf(
        blocks_json_b64,
        initial_superpose=initial_superpose,
        initial_conf_index=initial_conf_index,
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}}
    #v{{position:relative;}}
    #chem-conf-legend{{
      display:none;position:absolute;top:8px;right:8px;z-index:20;
      max-width:168px;max-height:calc(100% - 16px);overflow:auto;
      font:12px/1.35 system-ui,Segoe UI,sans-serif;
      background:rgba(255,255,255,0.94);border:1px solid #c8c8c8;border-radius:8px;
      box-shadow:0 2px 8px rgba(0,0,0,.12);padding:8px 10px;
    }}
  </style>
</head>
<body>
  <div id="v"></div>
  <div id="chem-conf-legend"></div>
{resize_scheduler_binding_html(RESIZE_KEEP_ZOOM_JS)}
{_reset_structure_menu_html()}
{init}
  <script src="{script_src}" onload="molmanagerInitView()"></script>
</body>
</html>"""
