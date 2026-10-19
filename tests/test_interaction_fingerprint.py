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

"""Interaction fingerprint tokens from typed residue contacts."""

from __future__ import annotations

from molmanager.protein.interaction_fingerprint import (
    fingerprint_from_contacts,
    fingerprint_headers,
    residue_label,
)
from molmanager.protein.protein_interactions import ProteinInteraction
from molmanager.ui.main_window.menu_spec import MAIN_WINDOW_MENUS, find_submenu, menu_outline


def _contact(family: str, chain: str, resn: str, resi: str, icode: str = "") -> ProteinInteraction:
    return ProteinInteraction(
        family=family,
        interaction=family,
        start=(0.0, 0.0, 0.0),
        end=(1.0, 0.0, 0.0),
        distance=2.0,
        ligand_chain="Z",
        ligand_resn="LIG",
        ligand_resi="1",
        ligand_icode="",
        ligand_name="C1",
        ligand_kind="ligand",
        protein_chain=chain,
        protein_resn=resn,
        protein_resi=resi,
        protein_icode=icode,
        protein_name="CA",
        protein_kind="polymer",
    )


def test_fingerprint_collapses_duplicate_contacts_and_sorts():
    fingerprint, residues = fingerprint_from_contacts(
        [
            _contact("hydrophobic", "A", "PHE", "45"),
            _contact("hbond", "A", "ASP", "123"),
            _contact("hbond", "A", "ASP", "123"),
            _contact("vdw", "A", "GLY", "1"),
        ]
    )
    assert fingerprint == "A:ASP:123:hbond;A:PHE:45:hydrophobic"
    assert residues == "A:ASP:123;A:PHE:45"
    assert residue_label("A", "ASP", "123", "A") == "A:ASP:123:A"
    assert fingerprint_headers("IFP") == ("IFP", "IFP Residues")
    assert fingerprint_headers("  ") == ("IFP", "IFP Residues")


def test_empty_contacts_are_blank():
    assert fingerprint_from_contacts(()) == ("", "")


def test_interaction_fingerprint_sits_on_the_protein_menu():
    protein = find_submenu(MAIN_WINDOW_MENUS, "Protein")
    labels = [x if isinstance(x, str) else next(iter(x)) for x in menu_outline(protein.items)]
    assert labels.index("Interaction Fingerprint…") == labels.index("Dock Ligand") + 1
