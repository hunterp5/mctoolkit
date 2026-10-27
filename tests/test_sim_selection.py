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

"""Selection language used by restraints and observables."""

from molmanager.sim.selection import (
    AtomRecord,
    SelectionError,
    atoms_from_structure_text,
    select_atom_indices,
)


def _atom(index, name, resname, chain, resi, element, kind, x=0.0, y=0.0, z=0.0):
    return AtomRecord(
        index=index,
        name=name,
        resname=resname,
        chain=chain,
        resi=resi,
        element=element,
        kind=kind,
        x=x,
        y=y,
        z=z,
    )


def _pocket():
    return [
        _atom(0, "CA", "ALA", "A", 10, "C", "protein", 0, 0, 0),
        _atom(1, "CB", "ALA", "A", 10, "C", "protein", 1.5, 0, 0),
        _atom(2, "N", "ALA", "A", 11, "N", "protein", 0, 1.5, 0),
        _atom(3, "C1", "LIG", "B", 1, "C", "ligand", 3.0, 0, 0),
        _atom(4, "O1", "HOH", "W", 2, "O", "water", 8, 0, 0),
        _atom(5, "H1", "ALA", "A", 10, "H", "protein", 0.2, 0.2, 0),
    ]


def test_words_qualifiers_and_within():
    atoms = _pocket()
    assert select_atom_indices("protein and not hydrogen", atoms) == [0, 1, 2]
    assert select_atom_indices("ca", atoms) == [0]
    assert select_atom_indices("sidechain", atoms) == [1]
    assert select_atom_indices("ligand or water", atoms) == [3, 4]
    assert select_atom_indices("chain A and resi 10-11", atoms) == [0, 1, 2, 5]
    assert select_atom_indices("within 2 of ligand", atoms) == [1, 3]
    assert select_atom_indices("id 4", atoms) == [4]
    assert select_atom_indices("not (ligand or water)", atoms) == [0, 1, 2, 5]


def test_unknown_word_names_the_token():
    try:
        select_atom_indices("backbone and foo", _pocket())
    except SelectionError as exc:
        assert exc.token == "foo"
    else:
        raise AssertionError("expected SelectionError")


def test_pdb_text_infers_ligand_and_water():
    text = (
        "ATOM      1  CA  ALA A  10       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  O   HOH A  99       4.000   0.000   0.000  1.00  0.00           O\n"
        "HETATM    3  C1  LIG B   1       6.000   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    atoms = atoms_from_structure_text(text, "pdb")
    assert [atom.kind for atom in atoms] == ["protein", "water", "ligand"]
    assert select_atom_indices("name CA", atoms) == [0]
