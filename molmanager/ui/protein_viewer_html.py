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


"""3Dmol.js page assembly for the protein viewer."""

from __future__ import annotations

from pathlib import Path

from .mol_3d_html import (
    _RESET_STRUCTURE_JS,
    RESIZE_KEEP_VIEW_JS,
    assemble_3dmol_shell_page,
    bundled_3dmol_available,
)

_PROTEIN_VIEWER_JS_PATH = Path(__file__).with_name("protein_viewer.js")


def _viewer_protein_init_script() -> str:
    js = _PROTEIN_VIEWER_JS_PATH.read_text(encoding="utf-8")
    return (
        "  <script>\n"
        + js.replace("__RESET_JS__", _RESET_STRUCTURE_JS).rstrip("\n")
        + "\n  </script>"
    )


def _assemble_protein_page(*, script_src: str) -> str:
    return assemble_3dmol_shell_page(
        script_src=script_src,
        init_html=_viewer_protein_init_script(),
        extra_scripts='  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>\n',
        background="#fff",
        resize_js=RESIZE_KEEP_VIEW_JS,
    )


def build_protein_viewer_html() -> str:
    """Return the protein 3Dmol page (offline bundle when available)."""
    if bundled_3dmol_available():
        return _assemble_protein_page(script_src="3Dmol-min.js")
    return _assemble_protein_page(script_src="https://3dmol.org/build/3Dmol-min.js")
