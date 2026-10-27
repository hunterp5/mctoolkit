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

"""tleap text for split topologies, box shape, water, and ions."""

import pytest

from molmanager.sim.system_build import SystemBuildError, leap_script


def test_leap_script_writes_split_topologies_and_a_tip3p_box():
    text = leap_script(
        protein_pdb="protein.pdb",
        ligands=(("lig0_gaff.mol2", "lig0.frcmod", "LIG"),),
        protein_ff="ff14sb",
        ligand_ff="gaff2",
        solvent="tip3p",
        box_shape="octahedron",
        padding_a=12.0,
        ion_mode="concentration",
        ion_conc_m=0.15,
        cation="Na+",
        anion="Cl-",
    )
    assert "saveAmberParm PROT receptor.prmtop receptor.inpcrd" in text
    assert "saveAmberParm LIG0 ligand.prmtop ligand.inpcrd" in text
    assert "saveAmberParm COMP complex_dry.prmtop complex_dry.inpcrd" in text
    assert "source leaprc.water.tip3p" in text
    assert "solvateOct COMP TIP3PBOX 12.000" in text
    assert "addIonsRand COMP Na+ 0 Cl- 0 0.1500" in text
    assert "source leaprc.protein.ff14SB" in text
    assert "source leaprc.gaff2" in text


def test_leap_script_neutralize_and_cubic_box():
    text = leap_script(
        protein_pdb="protein.pdb",
        ligands=(("lig.mol2", "lig.frcmod", "LIG"),),
        protein_ff="ff99sbildn",
        ligand_ff="gaff",
        solvent="opc",
        box_shape="cubic",
        ion_mode="neutralize",
        cation="K+",
    )
    assert "solvateBox COMP OPCBOX" in text
    assert "addIons COMP K+ 0" in text
    assert "source oldff/leaprc.ff99SBildn" in text


def test_leap_script_refuses_a_gaff_dodecahedron():
    with pytest.raises(SystemBuildError, match="dodecahedron"):
        leap_script(
            protein_pdb="protein.pdb",
            ligands=(),
            protein_ff="ff14sb",
            ligand_ff="gaff2",
            solvent="tip3p",
            box_shape="dodecahedron",
        )
