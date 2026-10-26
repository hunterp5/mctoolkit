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

"""Copy submenu shared by structure cells and structure depictions."""

from __future__ import annotations

from PyQt5.QtWidgets import QMenu

from ..chem.molecule_conversion import mol_structure_copy_texts

_STRUCTURE_COPY_FORMATS: tuple[tuple[str, str, str], ...] = (
    ("smiles", "SMILES", "Canonical isomeric SMILES."),
    ("inchi", "InChI", "Standard InChI."),
    ("inchikey", "InChIKey", "Standard InChIKey."),
    ("molfile", "Molfile", "MDL molfile (V2000)."),
    ("smarts", "SMARTS", "Daylight SMARTS."),
)


def add_structure_copy_submenu(menu: QMenu, mol) -> dict:
    """Add Copy → SMILES, InChI, InChIKey, Molfile, and SMARTS.

    Returns each enabled action mapped to ``(clipboard text, status message)``.
    """
    copy_menu = menu.addMenu("Copy")
    copy_menu.setToolTipsVisible(True)
    texts = mol_structure_copy_texts(mol)
    by_act: dict = {}
    for key, label, tooltip in _STRUCTURE_COPY_FORMATS:
        act = copy_menu.addAction(label)
        act.setObjectName(f"copy_format_{key}")
        act.setToolTip(tooltip)
        txt = texts.get(key) or ""
        usable = bool(txt.strip())
        act.setEnabled(usable)
        if usable:
            status = (
                "Copied canonical SMILES to clipboard."
                if key == "smiles"
                else f"Copied {label} to clipboard."
            )
            by_act[act] = (txt, status)
    return by_act
