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

"""Geometric hydrogen-bond detection for protein, ligand, and complex pairs."""

from __future__ import annotations

from molmanager.protein.hydrogen_bonds import (
    HBOND_KIND_COMPLEX,
    HBOND_KIND_LIGAND,
    HBOND_KIND_PROTEIN,
    detect_hydrogen_bonds,
)

_PROTEIN_INTRA = """\
ATOM      1  C   ALA A   1      -1.240   0.150   0.000  1.00  0.00           C
ATOM      2  O   ALA A   1       0.000   0.000   0.000  1.00  0.00           O
ATOM      3  N   ALA A   3       2.900   0.100   0.000  1.00  0.00           N
ATOM      4  CA  ALA A   3       4.000   0.400   0.000  1.00  0.00           C
END
"""

_PROTEIN_SEQUENTIAL = """\
ATOM      1  C   ALA A   1      -1.240   0.150   0.000  1.00  0.00           C
ATOM      2  O   ALA A   1       0.000   0.000   0.000  1.00  0.00           O
ATOM      3  N   ALA A   2       2.900   0.100   0.000  1.00  0.00           N
ATOM      4  CA  ALA A   2       4.000   0.400   0.000  1.00  0.00           C
END
"""

_PEPTIDE_COVALENT = """\
ATOM      1  C   ALA A   1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2  O   ALA A   1       1.230   0.000   0.000  1.00  0.00           O
ATOM      3  N   ALA A   2      -1.330   0.000   0.000  1.00  0.00           N
ATOM      4  CA  ALA A   2      -1.850   1.400   0.000  1.00  0.00           C
END
"""

_COMPLEX = """\
ATOM      1  CB  SER A  10      -1.430   0.400   0.000  1.00  0.00           C
ATOM      2  OG  SER A  10       0.000   0.000   0.000  1.00  0.00           O
HETATM  100  C1  LIG A  99       3.900   0.200   0.000  1.00  0.00           C
HETATM  101  O1  LIG A  99       2.800   0.100   0.000  1.00  0.00           O
END
"""

_LIGAND_INTRA = """\
HETATM  100  C1  LIG A  99      -1.220   0.000   0.000  1.00  0.00           C
HETATM  101  O1  LIG A  99       0.000   0.000   0.000  1.00  0.00           O
HETATM  102  C2  LIG A  99       4.000   0.200   0.000  1.00  0.00           C
HETATM  103  O2  LIG A  99       2.750   0.150   0.000  1.00  0.00           O
END
"""

_WITH_HYDROGEN = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      -0.720   1.200   0.000  1.00  0.00           C
ATOM      3  H   ALA A   1       1.010   0.000   0.000  1.00  0.00           H
ATOM      4  C   ALA A   4       4.050   0.200   0.000  1.00  0.00           C
ATOM      5  O   ALA A   4       2.850   0.050   0.000  1.00  0.00           O
END
"""

_WATER_NEAR_SER = """\
ATOM      1  CB  SER A  10      -1.430   0.400   0.000  1.00  0.00           C
ATOM      2  OG  SER A  10       0.000   0.000   0.000  1.00  0.00           O
HETATM  200  O   HOH A  50       2.800   0.100   0.000  1.00  0.00           O
END
"""


def test_detects_protein_intramolecular_backbone_hbond():
    bonds = detect_hydrogen_bonds(_PROTEIN_INTRA, "pdb")
    assert len(bonds) == 1
    bond = bonds[0]
    assert bond.kind == HBOND_KIND_PROTEIN
    assert {bond.donor_name, bond.acceptor_name} == {"N", "O"}
    assert bond.has_hydrogen is False
    assert 2.5 < bond.distance < 3.5


def test_skips_adjacent_backbone_and_peptide_covalent_pairs():
    assert detect_hydrogen_bonds(_PROTEIN_SEQUENTIAL, "pdb") == ()
    assert detect_hydrogen_bonds(_PEPTIDE_COVALENT, "pdb") == ()


def test_detects_protein_ligand_hbond():
    bonds = detect_hydrogen_bonds(_COMPLEX, "pdb")
    assert len(bonds) == 1
    bond = bonds[0]
    assert bond.kind == HBOND_KIND_COMPLEX
    assert {bond.donor_kind, bond.acceptor_kind} == {"polymer", "ligand"}
    names = {bond.donor_name, bond.acceptor_name}
    assert "OG" in names
    assert "O1" in names
    assert bond.to_payload()["showResidues"] == [
        {"chain": "A", "resn": "SER", "resi": "10", "icode": ""}
    ]


def test_detects_ligand_intramolecular_hbond():
    bonds = detect_hydrogen_bonds(_LIGAND_INTRA, "pdb")
    assert len(bonds) == 1
    bond = bonds[0]
    assert bond.kind == HBOND_KIND_LIGAND
    assert {bond.donor_name, bond.acceptor_name} == {"O1", "O2"}
    payload = bond.to_payload()
    assert payload["kind"] == HBOND_KIND_LIGAND
    assert "start" in payload and "end" in payload
    assert payload["color"].startswith("#")


def test_uses_explicit_hydrogen_geometry():
    bonds = detect_hydrogen_bonds(_WITH_HYDROGEN, "pdb")
    assert len(bonds) == 1
    bond = bonds[0]
    assert bond.kind == HBOND_KIND_PROTEIN
    assert bond.has_hydrogen is True
    assert bond.distance < 2.5
    assert bond.angle is not None and bond.angle >= 120.0
    assert bond.start[0] == 1.01


def test_ignores_water_contacts():
    assert detect_hydrogen_bonds(_WATER_NEAR_SER, "pdb") == ()


# Sulfonyl O1 sits 2.7 Å from Asn OD1. S is the only heavy neighbor of O1.
_SULFONYL_NO_HYDROGEN = """\
ATOM      1  CG  ASN A 142      -1.400   0.000   0.000  1.00  0.00           C
ATOM      2  OD1 ASN A 142       0.000   0.000   0.000  1.00  0.00           O
HETATM  100  S   LIG A 289       4.050   0.150   0.000  1.00  0.00           S
HETATM  101  O1  LIG A 289       2.700   0.100   0.000  1.00  0.00           O
END
"""

# Same sulfonyl, plus a carbon-bound hydrogen so the ligand counts as protonated,
# and a serine hydroxyl hydrogen aimed at O1.
_SULFONYL_PROTONATED = """\
ATOM      1  CB  SER A  10      -1.430   0.400   0.000  1.00  0.00           C
ATOM      2  OG  SER A  10       0.000   0.000   0.000  1.00  0.00           O
ATOM      3  HG  SER A  10       0.900   0.000   0.000  1.00  0.00           H
HETATM  100  S   LIG A 289       4.050   0.150   0.000  1.00  0.00           S
HETATM  101  O1  LIG A 289       2.700   0.100   0.000  1.00  0.00           O
HETATM  102  C1  LIG A 289       5.400   0.150   0.000  1.00  0.00           C
HETATM  103  H1  LIG A 289       5.400   1.200   0.000  1.00  0.00           H
END
"""


def test_sulfonyl_oxygen_without_hydrogen_is_not_a_donor():
    assert detect_hydrogen_bonds(_SULFONYL_NO_HYDROGEN, "pdb") == ()


def test_protonated_sulfonyl_oxygen_accepts_and_does_not_donate():
    bonds = detect_hydrogen_bonds(_SULFONYL_PROTONATED, "pdb")
    assert len(bonds) == 1
    bond = bonds[0]
    assert bond.kind == HBOND_KIND_COMPLEX
    assert bond.donor_resn == "SER"
    assert bond.donor_name == "OG"
    assert bond.acceptor_resn == "LIG"
    assert bond.acceptor_name == "O1"
    assert bond.has_hydrogen is True
    assert bond.to_payload()["showResidues"] == [
        {"chain": "A", "resn": "SER", "resi": "10", "icode": ""}
    ]
