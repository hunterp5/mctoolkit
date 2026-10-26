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

"""Named bioisostere transforms for one-at-a-time analog design.

Each entry is a single-reactant SMIRKS reaction that replaces one group and
leaves the rest of the molecule alone. The set is the replacements a medicinal
chemist tries on purpose (classical isosteres, ring swaps, linker swaps, and
the usual halogen / methyl / aza scans). It is not a matched-pair database:
there is no frequency and no assay delta on a row.

Applying one transform returns every distinct single replacement. It does not
combine several sites in one product. Deuteration is omitted so site-of-metabolism
blocking can own that edit. Amide patterns require a secondary amide whose
N-substituent is not itself a carbonyl, so imides are left alone. Carboxylic-acid
patterns require an OH, so esters are left alone.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem import AllChem

# Secondary amide whose N-substituent carbon is not a carbonyl (drops imides).
_AMIDE = "[#6:1][CX3](=O)[NX3H1][#6;!$(C=O):2]"
_AMIDE_MAPPED = "[#6:1][C:3](=[O:4])[NX3H1:5][#6;!$(C=O):2]"
_ACID = "[#6:1][CX3](=O)[OX2H1]"
# Methyl attached only to carbon, so methoxy / N-methyl / S-methyl stay put.
_C_METHYL = "[CX4H3;!$(C~[!#6]):1]"
_LINKER_ATOM = "#6;!$([CH3]);!$(C=O)"


@dataclass(frozen=True)
class Bioisostere:
    """One named, one-direction replacement."""

    key: str
    name: str
    category: str
    smirks: str
    summary: str
    example_in: str
    example_out: str


CATEGORY_LABELS: dict[str, str] = {
    "aromatic_hydrogen": "Aromatic hydrogen",
    "halogen_methyl": "Halogen and methyl",
    "polar_substituent": "Hydroxyl, alkoxy, thiol, amino",
    "alkyl": "Alkyl and tert-butyl",
    "carboxylic_acid": "Carboxylic acid",
    "amide": "Amide and ester",
    "phenyl": "Phenyl replacements",
    "ring_heteroatom": "Ring heteroatom",
    "saturated_ring": "Saturated rings",
    "linker": "Linkers",
    "basic_polar": "Basic and polar groups",
}


def _row(
    key: str,
    name: str,
    category: str,
    smirks: str,
    summary: str,
    example_in: str,
    example_out: str,
) -> Bioisostere:
    return Bioisostere(key, name, category, smirks, summary, example_in, example_out)


BIOISOSTERES: tuple[Bioisostere, ...] = (
    # --- Aromatic hydrogen: one CH becomes the new substituent. ---
    _row(
        "aryl_h_to_f",
        "Aromatic H to F",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]F",
        "Replace one aromatic hydrogen with fluorine.",
        "c1ccccc1",
        "Fc1ccccc1",
    ),
    _row(
        "aryl_h_to_cl",
        "Aromatic H to Cl",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]Cl",
        "Replace one aromatic hydrogen with chlorine.",
        "c1ccccc1",
        "Clc1ccccc1",
    ),
    _row(
        "aryl_h_to_me",
        "Aromatic H to methyl",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]C",
        "Replace one aromatic hydrogen with a methyl group.",
        "c1ccccc1",
        "Cc1ccccc1",
    ),
    _row(
        "aryl_h_to_cf3",
        "Aromatic H to CF3",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]C(F)(F)F",
        "Replace one aromatic hydrogen with trifluoromethyl.",
        "c1ccccc1",
        "FC(F)(F)c1ccccc1",
    ),
    _row(
        "aryl_h_to_cn",
        "Aromatic H to CN",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]C#N",
        "Replace one aromatic hydrogen with a nitrile.",
        "c1ccccc1",
        "N#Cc1ccccc1",
    ),
    _row(
        "aryl_h_to_oh",
        "Aromatic H to OH",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]O",
        "Replace one aromatic hydrogen with a hydroxyl.",
        "c1ccccc1",
        "Oc1ccccc1",
    ),
    _row(
        "aryl_h_to_ome",
        "Aromatic H to methoxy",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]OC",
        "Replace one aromatic hydrogen with a methoxy group.",
        "c1ccccc1",
        "COc1ccccc1",
    ),
    _row(
        "aryl_h_to_nh2",
        "Aromatic H to NH2",
        "aromatic_hydrogen",
        "[cH:1]>>[c:1]N",
        "Replace one aromatic hydrogen with a primary amine.",
        "c1ccccc1",
        "Nc1ccccc1",
    ),
    _row(
        "aryl_ch_to_n",
        "Aromatic CH to N",
        "aromatic_hydrogen",
        "[cH:1]>>[n:1]",
        "Replace one aromatic CH with nitrogen. Benzene gives pyridine; "
        "each distinct site is returned separately.",
        "c1ccccc1",
        "c1ccncc1",
    ),
    _row(
        "aryl_ortho_diaza",
        "Adjacent aromatic CH to N-N",
        "aromatic_hydrogen",
        "[cH:1][cH:2]>>[n:1][n:2]",
        "Replace one pair of adjacent aromatic CH groups with nitrogen. Benzene gives pyridazine.",
        "c1ccccc1",
        "c1ccnnc1",
    ),
    _row(
        "aryl_meta_diaza",
        "Meta aromatic CH to N",
        "aromatic_hydrogen",
        "[cH:1][c:2][cH:3]>>[n:1][c:2][n:3]",
        "Replace two aromatic CH groups separated by one atom with nitrogen. "
        "Benzene gives pyrimidine.",
        "c1ccccc1",
        "c1cncnc1",
    ),
    _row(
        "aryl_para_diaza",
        "Para aromatic CH to N",
        "aromatic_hydrogen",
        "[cH:1][c:2][c:3][cH:4]>>[n:1][c:2][c:3][n:4]",
        "Replace two aromatic CH groups separated by two atoms with nitrogen. "
        "Benzene gives pyrazine.",
        "c1ccccc1",
        "c1cnccn1",
    ),
    # --- Halogen and methyl swaps on an aryl ring. ---
    _row(
        "aryl_f_to_cl",
        "Aryl F to Cl",
        "halogen_methyl",
        "[c:1]F>>[c:1]Cl",
        "Replace an aromatic fluorine with chlorine.",
        "Fc1ccccc1",
        "Clc1ccccc1",
    ),
    _row(
        "aryl_cl_to_f",
        "Aryl Cl to F",
        "halogen_methyl",
        "[c:1]Cl>>[c:1]F",
        "Replace an aromatic chlorine with fluorine.",
        "Clc1ccccc1",
        "Fc1ccccc1",
    ),
    _row(
        "aryl_cl_to_br",
        "Aryl Cl to Br",
        "halogen_methyl",
        "[c:1]Cl>>[c:1]Br",
        "Replace an aromatic chlorine with bromine.",
        "Clc1ccccc1",
        "Brc1ccccc1",
    ),
    _row(
        "aryl_br_to_cl",
        "Aryl Br to Cl",
        "halogen_methyl",
        "[c:1]Br>>[c:1]Cl",
        "Replace an aromatic bromine with chlorine.",
        "Brc1ccccc1",
        "Clc1ccccc1",
    ),
    _row(
        "aryl_br_to_i",
        "Aryl Br to I",
        "halogen_methyl",
        "[c:1]Br>>[c:1]I",
        "Replace an aromatic bromine with iodine.",
        "Brc1ccccc1",
        "Ic1ccccc1",
    ),
    _row(
        "aryl_i_to_br",
        "Aryl I to Br",
        "halogen_methyl",
        "[c:1]I>>[c:1]Br",
        "Replace an aromatic iodine with bromine.",
        "Ic1ccccc1",
        "Brc1ccccc1",
    ),
    _row(
        "aryl_f_to_h",
        "Aryl F to H",
        "halogen_methyl",
        "[c:1]F>>[cH:1]",
        "Replace an aromatic fluorine with hydrogen.",
        "Fc1ccccc1",
        "c1ccccc1",
    ),
    _row(
        "aryl_cl_to_me",
        "Aryl Cl to methyl",
        "halogen_methyl",
        "[c:1]Cl>>[c:1]C",
        "Replace an aromatic chlorine with a methyl group.",
        "Clc1ccccc1",
        "Cc1ccccc1",
    ),
    _row(
        "aryl_me_to_cl",
        "Aryl methyl to Cl",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]Cl",
        "Replace an aromatic methyl with chlorine.",
        "Cc1ccccc1",
        "Clc1ccccc1",
    ),
    _row(
        "aryl_me_to_f",
        "Aryl methyl to F",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]F",
        "Replace an aromatic methyl with fluorine.",
        "Cc1ccccc1",
        "Fc1ccccc1",
    ),
    _row(
        "aryl_me_to_cf3",
        "Aryl methyl to CF3",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]C(F)(F)F",
        "Replace an aromatic methyl with trifluoromethyl.",
        "Cc1ccccc1",
        "FC(F)(F)c1ccccc1",
    ),
    _row(
        "aryl_cf3_to_me",
        "Aryl CF3 to methyl",
        "halogen_methyl",
        "[c:1]C(F)(F)F>>[c:1]C",
        "Replace an aromatic trifluoromethyl with methyl.",
        "FC(F)(F)c1ccccc1",
        "Cc1ccccc1",
    ),
    _row(
        "aryl_me_to_ch2f",
        "Aryl methyl to CH2F",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]CF",
        "Replace an aromatic methyl with fluoromethyl.",
        "Cc1ccccc1",
        "FCc1ccccc1",
    ),
    _row(
        "aryl_me_to_chf2",
        "Aryl methyl to CHF2",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]C(F)F",
        "Replace an aromatic methyl with difluoromethyl.",
        "Cc1ccccc1",
        "FC(F)c1ccccc1",
    ),
    _row(
        "aryl_me_to_cn",
        "Aryl methyl to CN",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]C#N",
        "Replace an aromatic methyl with a nitrile.",
        "Cc1ccccc1",
        "N#Cc1ccccc1",
    ),
    _row(
        "aryl_me_to_oh",
        "Aryl methyl to OH",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]O",
        "Replace an aromatic methyl with a hydroxyl.",
        "Cc1ccccc1",
        "Oc1ccccc1",
    ),
    _row(
        "aryl_me_to_ome",
        "Aryl methyl to methoxy",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]OC",
        "Replace an aromatic methyl with a methoxy group.",
        "Cc1ccccc1",
        "COc1ccccc1",
    ),
    _row(
        "aryl_me_to_nh2",
        "Aryl methyl to NH2",
        "halogen_methyl",
        "[c:1][CH3]>>[c:1]N",
        "Replace an aromatic methyl with a primary amine.",
        "Cc1ccccc1",
        "Nc1ccccc1",
    ),
    _row(
        "aryl_cl_to_cf3",
        "Aryl Cl to CF3",
        "halogen_methyl",
        "[c:1]Cl>>[c:1]C(F)(F)F",
        "Replace an aromatic chlorine with trifluoromethyl.",
        "Clc1ccccc1",
        "FC(F)(F)c1ccccc1",
    ),
    _row(
        "aryl_cl_to_cn",
        "Aryl Cl to CN",
        "halogen_methyl",
        "[c:1]Cl>>[c:1]C#N",
        "Replace an aromatic chlorine with a nitrile.",
        "Clc1ccccc1",
        "N#Cc1ccccc1",
    ),
    _row(
        "aryl_cn_to_cl",
        "Aryl CN to Cl",
        "halogen_methyl",
        "[c:1]C#N>>[c:1]Cl",
        "Replace an aromatic nitrile with chlorine.",
        "N#Cc1ccccc1",
        "Clc1ccccc1",
    ),
    _row(
        "aryl_cl_to_ethynyl",
        "Aryl Cl to ethynyl",
        "halogen_methyl",
        "[c:1]Cl>>[c:1]C#C",
        "Replace an aromatic chlorine with an ethynyl group.",
        "Clc1ccccc1",
        "C#Cc1ccccc1",
    ),
    _row(
        "aryl_ethynyl_to_cl",
        "Aryl ethynyl to Cl",
        "halogen_methyl",
        "[c:1]C#C>>[c:1]Cl",
        "Replace an aromatic ethynyl group with chlorine.",
        "C#Cc1ccccc1",
        "Clc1ccccc1",
    ),
    _row(
        "aryl_ethynyl_to_cn",
        "Aryl ethynyl to CN",
        "halogen_methyl",
        "[c:1]C#C>>[c:1]C#N",
        "Replace an aromatic ethynyl group with a nitrile.",
        "C#Cc1ccccc1",
        "N#Cc1ccccc1",
    ),
    _row(
        "aryl_br_to_cf3",
        "Aryl Br to CF3",
        "halogen_methyl",
        "[c:1]Br>>[c:1]C(F)(F)F",
        "Replace an aromatic bromine with trifluoromethyl.",
        "Brc1ccccc1",
        "FC(F)(F)c1ccccc1",
    ),
    _row(
        "aryl_cf3_to_sf5",
        "Aryl CF3 to SF5",
        "halogen_methyl",
        "[c:1]C(F)(F)F>>[c:1]S(F)(F)(F)(F)F",
        "Replace an aromatic trifluoromethyl with pentafluorosulfanyl.",
        "FC(F)(F)c1ccccc1",
        "FS(F)(F)(F)(F)c1ccccc1",
    ),
    _row(
        "aryl_sf5_to_cf3",
        "Aryl SF5 to CF3",
        "halogen_methyl",
        "[c:1]S(F)(F)(F)(F)F>>[c:1]C(F)(F)F",
        "Replace an aromatic pentafluorosulfanyl with trifluoromethyl.",
        "FS(F)(F)(F)(F)c1ccccc1",
        "FC(F)(F)c1ccccc1",
    ),
    # --- OH, alkoxy, thiol, aniline. ---
    _row(
        "aryl_oh_to_f",
        "Aryl OH to F",
        "polar_substituent",
        "[c:1][OH]>>[c:1]F",
        "Replace an aromatic hydroxyl with fluorine.",
        "Oc1ccccc1",
        "Fc1ccccc1",
    ),
    _row(
        "aryl_oh_to_nh2",
        "Aryl OH to NH2",
        "polar_substituent",
        "[c:1][OH]>>[c:1]N",
        "Replace an aromatic hydroxyl with a primary amine.",
        "Oc1ccccc1",
        "Nc1ccccc1",
    ),
    _row(
        "aryl_nh2_to_oh",
        "Aryl NH2 to OH",
        "polar_substituent",
        "[c:1][NH2]>>[c:1]O",
        "Replace an aromatic primary amine with a hydroxyl.",
        "Nc1ccccc1",
        "Oc1ccccc1",
    ),
    _row(
        "aryl_nh2_to_f",
        "Aryl NH2 to F",
        "polar_substituent",
        "[c:1][NH2]>>[c:1]F",
        "Replace an aromatic primary amine with fluorine.",
        "Nc1ccccc1",
        "Fc1ccccc1",
    ),
    _row(
        "aryl_oh_to_sh",
        "Aryl OH to SH",
        "polar_substituent",
        "[c:1][OH]>>[c:1]S",
        "Replace an aromatic hydroxyl with a thiol.",
        "Oc1ccccc1",
        "Sc1ccccc1",
    ),
    _row(
        "aryl_sh_to_oh",
        "Aryl SH to OH",
        "polar_substituent",
        "[c:1][SH]>>[c:1]O",
        "Replace an aromatic thiol with a hydroxyl.",
        "Sc1ccccc1",
        "Oc1ccccc1",
    ),
    _row(
        "aryl_oh_to_ome",
        "Aryl OH to methoxy",
        "polar_substituent",
        "[c:1][OH]>>[c:1]OC",
        "Cap an aromatic hydroxyl as a methoxy group.",
        "Oc1ccccc1",
        "COc1ccccc1",
    ),
    _row(
        "aryl_ome_to_oh",
        "Aryl methoxy to OH",
        "polar_substituent",
        "[c:1][OX2][CH3]>>[c:1][OH]",
        "Cleave an aromatic methoxy group back to the phenol.",
        "COc1ccccc1",
        "Oc1ccccc1",
    ),
    _row(
        "aryl_ome_to_ocf3",
        "Aryl methoxy to OCF3",
        "polar_substituent",
        "[c:1][OX2][CH3]>>[c:1]OC(F)(F)F",
        "Replace an aromatic methoxy group with trifluoromethoxy.",
        "COc1ccccc1",
        "FC(F)(F)Oc1ccccc1",
    ),
    _row(
        "aryl_ocf3_to_ome",
        "Aryl OCF3 to methoxy",
        "polar_substituent",
        "[c:1]OC(F)(F)F>>[c:1]OC",
        "Replace an aromatic trifluoromethoxy with methoxy.",
        "FC(F)(F)Oc1ccccc1",
        "COc1ccccc1",
    ),
    _row(
        "aryl_ome_to_nhme",
        "Aryl methoxy to NHMe",
        "polar_substituent",
        "[c:1]OC>>[c:1]NC",
        "Replace an aromatic methoxy group with N-methylamine.",
        "COc1ccccc1",
        "CNc1ccccc1",
    ),
    _row(
        "aryl_sme_to_so2me",
        "Aryl SMe to SO2Me",
        "polar_substituent",
        "[c:1][SX2][CH3]>>[c:1]S(C)(=O)=O",
        "Oxidize an aromatic methyl sulfide to the methyl sulfone.",
        "CSc1ccccc1",
        "CS(=O)(=O)c1ccccc1",
    ),
    _row(
        "aryl_so2me_to_sme",
        "Aryl SO2Me to SMe",
        "polar_substituent",
        "[c:1]S(C)(=O)=O>>[c:1]SC",
        "Reduce an aromatic methyl sulfone to the methyl sulfide.",
        "CS(=O)(=O)c1ccccc1",
        "CSc1ccccc1",
    ),
    _row(
        "aryl_sme_to_scf3",
        "Aryl SMe to SCF3",
        "polar_substituent",
        "[c:1][SX2][CH3]>>[c:1]SC(F)(F)F",
        "Replace an aromatic methyl sulfide with trifluoromethyl sulfide.",
        "CSc1ccccc1",
        "FC(F)(F)Sc1ccccc1",
    ),
    _row(
        "aryl_sme_to_ome",
        "Aryl SMe to OMe",
        "polar_substituent",
        "[c:1][SX2][CH3]>>[c:1]OC",
        "Replace an aromatic methyl sulfide with a methoxy group.",
        "CSc1ccccc1",
        "COc1ccccc1",
    ),
    # --- Alkyl and tert-butyl. ---
    _row(
        "c_methyl_to_fluoromethyl",
        "C-methyl to fluoromethyl",
        "alkyl",
        f"{_C_METHYL}>>[CX4H2:1]F",
        "Replace one hydrogen of a carbon-bound methyl with fluorine. "
        "Methoxy, N-methyl, and S-methyl groups are not matched.",
        "CC",
        "CCF",
    ),
    _row(
        "alkyl_oh_to_f",
        "Alkyl OH to F",
        "alkyl",
        "[CX4:1][OH]>>[CX4:1]F",
        "Replace an aliphatic hydroxyl with fluorine.",
        "CCO",
        "CCF",
    ),
    _row(
        "alkyl_nh2_to_oh",
        "Alkyl NH2 to OH",
        "alkyl",
        "[CX4:1][NH2]>>[CX4:1]O",
        "Replace an aliphatic primary amine with a hydroxyl.",
        "CCN",
        "CCO",
    ),
    _row(
        "tert_butyl_to_oxetane",
        "tert-Butyl to oxetan-3-yl",
        "alkyl",
        "[!#1:1][C]([CH3])([CH3])[CH3]>>[!#1:1]C1COC1",
        "Replace a tert-butyl group with oxetan-3-yl.",
        "CC(C)(C)c1ccccc1",
        "c1ccc(C2COC2)cc1",
    ),
    _row(
        "oxetane_to_tert_butyl",
        "Oxetan-3-yl to tert-butyl",
        "alkyl",
        "[!#1:1]C1COC1>>[!#1:1]C(C)(C)C",
        "Replace a 3-substituted oxetane with a tert-butyl group.",
        "c1ccc(C2COC2)cc1",
        "CC(C)(C)c1ccccc1",
    ),
    _row(
        "tert_butyl_to_bcp",
        "tert-Butyl to bicyclo[1.1.1]pentan-1-yl",
        "alkyl",
        "[!#1:1][C]([CH3])([CH3])[CH3]>>[!#1:1]C12CC(C1)C2",
        "Replace a tert-butyl group with bicyclo[1.1.1]pentan-1-yl.",
        "CC(C)(C)c1ccccc1",
        "c1ccc(C23CC(C2)C3)cc1",
    ),
    _row(
        "bcp_to_tert_butyl",
        "Bicyclo[1.1.1]pentan-1-yl to tert-butyl",
        "alkyl",
        "[!#1:1]C12CC(C1)C2>>[!#1:1]C(C)(C)C",
        "Replace a monosubstituted bicyclo[1.1.1]pentane with tert-butyl.",
        "c1ccc(C23CC(C2)C3)cc1",
        "CC(C)(C)c1ccccc1",
    ),
    _row(
        "tert_butyl_to_cf3",
        "tert-Butyl to CF3",
        "alkyl",
        "[!#1:1][C]([CH3])([CH3])[CH3]>>[!#1:1]C(F)(F)F",
        "Replace a tert-butyl group with trifluoromethyl.",
        "CC(C)(C)c1ccccc1",
        "FC(F)(F)c1ccccc1",
    ),
    _row(
        "gem_dimethyl_to_cyclopropane",
        "gem-Dimethyl to cyclopropane",
        "alkyl",
        "[#6:1][C:3]([CH3])([CH3])[#6:2]>>[#6:1][C:3]1([#6:2])CC1",
        "Tie the two methyl groups of a gem-dimethyl into a cyclopropane. "
        "The two other substituents stay on the same carbon.",
        "CC(C)(C)C",
        "CC1(C)CC1",
    ),
    # --- Carboxylic acid isosteres. The acid carbon's neighbor is carbon. ---
    _row(
        "acid_to_tetrazole",
        "Carboxylic acid to tetrazole",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]c1nn[nH]n1",
        "Replace a carboxylic acid with 1H-tetrazol-5-yl.",
        "c1ccc(C(=O)O)cc1",
        "c1ccc(-c2nn[nH]n2)cc1",
    ),
    _row(
        "tetrazole_to_acid",
        "Tetrazole to carboxylic acid",
        "carboxylic_acid",
        "[#6:1]c1nn[nH]n1>>[#6:1]C(=O)O",
        "Replace a 5-substituted 1H-tetrazole with a carboxylic acid.",
        "Cc1nn[nH]n1",
        "CC(=O)O",
    ),
    _row(
        "acid_to_acylsulfonamide",
        "Carboxylic acid to acylsulfonamide",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]C(=O)NS(C)(=O)=O",
        "Replace a carboxylic acid with an N-acylmethanesulfonamide.",
        "CC(=O)O",
        "CC(=O)NS(C)(=O)=O",
    ),
    _row(
        "acid_to_hydroxamic",
        "Carboxylic acid to hydroxamic acid",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]C(=O)NO",
        "Replace a carboxylic acid with a hydroxamic acid.",
        "CC(=O)O",
        "CC(=O)NO",
    ),
    _row(
        "hydroxamic_to_acid",
        "Hydroxamic acid to carboxylic acid",
        "carboxylic_acid",
        "[#6:1]C(=O)NO>>[#6:1]C(=O)O",
        "Replace a hydroxamic acid with a carboxylic acid.",
        "CC(=O)NO",
        "CC(=O)O",
    ),
    _row(
        "acid_to_sulfonamide",
        "Carboxylic acid to sulfonamide",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]S(N)(=O)=O",
        "Replace a carboxylic acid with a primary sulfonamide.",
        "CC(=O)O",
        "CS(N)(=O)=O",
    ),
    _row(
        "sulfonamide_to_acid",
        "Sulfonamide to carboxylic acid",
        "carboxylic_acid",
        "[#6:1]S(=O)(=O)[NH2]>>[#6:1]C(=O)O",
        "Replace a primary sulfonamide with a carboxylic acid.",
        "CS(N)(=O)=O",
        "CC(=O)O",
    ),
    _row(
        "acid_to_sulfonic",
        "Carboxylic acid to sulfonic acid",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]S(=O)(=O)O",
        "Replace a carboxylic acid with a sulfonic acid.",
        "CC(=O)O",
        "CS(=O)(=O)O",
    ),
    _row(
        "acid_to_phosphonic",
        "Carboxylic acid to phosphonic acid",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]P(=O)(O)O",
        "Replace a carboxylic acid with a phosphonic acid.",
        "CC(=O)O",
        "CP(=O)(O)O",
    ),
    _row(
        "phosphonic_to_acid",
        "Phosphonic acid to carboxylic acid",
        "carboxylic_acid",
        "[#6:1]P(=O)(O)O>>[#6:1]C(=O)O",
        "Replace a phosphonic acid with a carboxylic acid.",
        "CP(=O)(O)O",
        "CC(=O)O",
    ),
    _row(
        "acid_to_boronic",
        "Carboxylic acid to boronic acid",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]B(O)O",
        "Replace a carboxylic acid with a boronic acid.",
        "CC(=O)O",
        "CB(O)O",
    ),
    _row(
        "acid_to_oxadiazolone",
        "Carboxylic acid to 1,2,4-oxadiazol-5-one",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]c1noc(=O)[nH]1",
        "Replace a carboxylic acid with 1,2,4-oxadiazol-5(4H)-one.",
        "CC(=O)O",
        "Cc1noc(=O)[nH]1",
    ),
    _row(
        "acid_to_oxadiazolethione",
        "Carboxylic acid to 1,2,4-oxadiazole-5-thione",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]c1noc(=S)[nH]1",
        "Replace a carboxylic acid with 1,2,4-oxadiazole-5-thione.",
        "CC(=O)O",
        "Cc1noc(=S)[nH]1",
    ),
    _row(
        "acid_to_isoxazolol",
        "Carboxylic acid to isoxazol-3-ol",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]c1cc(O)no1",
        "Replace a carboxylic acid with a 5-substituted isoxazol-3-ol.",
        "CC(=O)O",
        "Cc1cc(O)no1",
    ),
    _row(
        "acid_to_squarate",
        "Carboxylic acid to squaric acid",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]C1=C(O)C(=O)C1=O",
        "Replace a carboxylic acid with a 3-hydroxy-3-cyclobutene-1,2-dione.",
        "CC(=O)O",
        "Cc1c(O)c(=O)c1=O",
    ),
    _row(
        "acid_to_thiazolidinedione",
        "Carboxylic acid to thiazolidinedione",
        "carboxylic_acid",
        f"{_ACID}>>[#6:1]C1SC(=O)NC1=O",
        "Replace a carboxylic acid with a 5-substituted thiazolidine-2,4-dione.",
        "CC(=O)O",
        "CC1SC(=O)NC1=O",
    ),
    _row(
        "primary_amide_to_tetrazole",
        "Primary amide to tetrazole",
        "carboxylic_acid",
        "[#6:1]C(=O)[NH2]>>[#6:1]c1nn[nH]n1",
        "Replace a primary amide with 1H-tetrazol-5-yl.",
        "CC(=O)N",
        "Cc1nn[nH]n1",
    ),
    _row(
        "nitrile_to_tetrazole",
        "Nitrile to tetrazole",
        "carboxylic_acid",
        "[#6:1]C#N>>[#6:1]c1nn[nH]n1",
        "Replace a nitrile with 1H-tetrazol-5-yl.",
        "CC#N",
        "Cc1nn[nH]n1",
    ),
    # --- Secondary amides, and the ester that reverses one of them. ---
    _row(
        "amide_reversal",
        "Secondary amide reversal",
        "amide",
        f"{_AMIDE_MAPPED}>>[#6:1][NX3H1:5][C:3](=[O:4])[#6:2]",
        "Reverse a secondary amide so the carbonyl and the NH trade places.",
        "CC(=O)Nc1ccccc1",
        "CNC(=O)c1ccccc1",
    ),
    _row(
        "amide_to_thioamide",
        "Secondary amide to thioamide",
        "amide",
        f"{_AMIDE}>>[#6:1]C(=S)[NX3H1][#6:2]",
        "Replace a secondary amide oxygen with sulfur.",
        "CC(=O)Nc1ccccc1",
        "CC(=S)Nc1ccccc1",
    ),
    _row(
        "amide_to_ester",
        "Secondary amide to ester",
        "amide",
        f"{_AMIDE}>>[#6:1]C(=O)O[#6:2]",
        "Replace a secondary amide NH with oxygen.",
        "CC(=O)Nc1ccccc1",
        "CC(=O)Oc1ccccc1",
    ),
    _row(
        "ester_to_amide",
        "Ester to secondary amide",
        "amide",
        "[#6:1]C(=O)O[#6:2]>>[#6:1]C(=O)N[#6:2]",
        "Replace an ester oxygen with NH. Lactones become lactams.",
        "CC(=O)OC",
        "CNC(C)=O",
    ),
    _row(
        "amide_to_sulfonamide",
        "Secondary amide to sulfonamide",
        "amide",
        f"{_AMIDE}>>[#6:1]S(=O)(=O)N[#6:2]",
        "Replace a secondary amide with a sulfonamide, carbonyl carbon becoming sulfur.",
        "CC(=O)Nc1ccccc1",
        "CS(=O)(=O)Nc1ccccc1",
    ),
    _row(
        "amide_to_reverse_sulfonamide",
        "Secondary amide to reverse sulfonamide",
        "amide",
        f"{_AMIDE}>>[#6:1]NS(=O)(=O)[#6:2]",
        "Replace a secondary amide with the reversed sulfonamide.",
        "CC(=O)Nc1ccccc1",
        "CNS(=O)(=O)c1ccccc1",
    ),
    _row(
        "amide_to_ketone",
        "Secondary amide to ketone",
        "amide",
        f"{_AMIDE}>>[#6:1]C(=O)[#6:2]",
        "Replace a secondary amide NH with a direct carbonyl-carbon bond.",
        "CC(=O)NC",
        "CC(C)=O",
    ),
    _row(
        "amide_to_n_methyl",
        "Secondary amide to N-methyl amide",
        "amide",
        f"{_AMIDE}>>[#6:1]C(=O)N(C)[#6:2]",
        "Methylate the nitrogen of a secondary amide.",
        "CC(=O)NC",
        "CC(=O)N(C)C",
    ),
    _row(
        "amide_to_urea",
        "Secondary amide to urea",
        "amide",
        f"{_AMIDE}>>[#6:1]NC(=O)N[#6:2]",
        "Insert NH between the acyl substituent and the carbonyl, giving a urea.",
        "CC(=O)NC",
        "CNC(=O)NC",
    ),
    _row(
        "amide_to_fluoroalkene",
        "Secondary amide to fluoroalkene",
        "amide",
        f"{_AMIDE}>>[#6:1]C(F)=C[#6:2]",
        "Replace a secondary amide with a fluoroalkene. E/Z is not assigned.",
        "CC(=O)NC",
        "CC=C(C)F",
    ),
    _row(
        "amide_to_trifluoroethylamine",
        "Secondary amide to trifluoroethylamine",
        "amide",
        f"{_AMIDE}>>[#6:1]C(C(F)(F)F)N[#6:2]",
        "Replace a secondary amide with a 1-trifluoromethyl amine. "
        "The new stereocenter is racemic.",
        "CC(=O)NC",
        "CNC(C)C(F)(F)F",
    ),
    _row(
        "amide_to_1_4_triazole",
        "Secondary amide to 1,4-triazole",
        "amide",
        f"{_AMIDE}>>[#6:1]c1cn([#6:2])nn1",
        "Replace a secondary amide with a 1,4-disubstituted 1,2,3-triazole. "
        "The acyl substituent goes to carbon and the N-substituent stays on nitrogen.",
        "CC(=O)Nc1ccccc1",
        "Cc1cn(-c2ccccc2)nn1",
    ),
    _row(
        "amide_to_1_5_triazole",
        "Secondary amide to 1,5-triazole",
        "amide",
        f"{_AMIDE}>>[#6:1]c1nn([#6:2])nc1",
        "Replace a secondary amide with a 1,5-disubstituted 1,2,3-triazole.",
        "CC(=O)Nc1ccccc1",
        "Cc1cnn(-c2ccccc2)n1",
    ),
    _row(
        "amide_to_1_2_4_oxadiazole",
        "Secondary amide to 3,5-oxadiazole",
        "amide",
        f"{_AMIDE}>>[#6:1]c1noc([#6:2])n1",
        "Replace a secondary amide with a 1,2,4-oxadiazole, acyl substituent on C5.",
        "CC(=O)Nc1ccccc1",
        "Cc1noc(-c2ccccc2)n1",
    ),
    _row(
        "amide_to_1_2_4_oxadiazole_alt",
        "Secondary amide to reversed 1,2,4-oxadiazole",
        "amide",
        f"{_AMIDE}>>[#6:1]c1nc([#6:2])no1",
        "Replace a secondary amide with the other 1,2,4-oxadiazole orientation.",
        "CC(=O)Nc1ccccc1",
        "Cc1nc(-c2ccccc2)no1",
    ),
    _row(
        "amide_to_1_3_4_oxadiazole",
        "Secondary amide to 1,3,4-oxadiazole",
        "amide",
        f"{_AMIDE}>>[#6:1]c1nnc([#6:2])o1",
        "Replace a secondary amide with a 1,3,4-oxadiazole.",
        "CC(=O)NC",
        "Cc1nnc(C)o1",
    ),
    _row(
        "amide_to_oxazole",
        "Secondary amide to oxazole",
        "amide",
        f"{_AMIDE}>>[#6:1]c1coc([#6:2])n1",
        "Replace a secondary amide with an oxazole.",
        "CC(=O)NC",
        "Cc1coc(C)n1",
    ),
    _row(
        "primary_amide_to_nitrile",
        "Primary amide to nitrile",
        "amide",
        "[#6:1]C(=O)[NH2]>>[#6:1]C#N",
        "Dehydrate a primary amide to a nitrile.",
        "CC(=O)N",
        "CC#N",
    ),
    _row(
        "carbamate_to_urea",
        "Carbamate to urea",
        "amide",
        "[#6:1][OX2]C(=O)[NX3H1][#6:2]>>[#6:1]NC(=O)N[#6:2]",
        "Replace the ether oxygen of a carbamate with NH, giving a urea.",
        "CCOC(=O)NC",
        "CCNC(=O)NC",
    ),
    _row(
        "urea_to_thiourea",
        "Urea to thiourea",
        "amide",
        "[NH:1]C(=O)[NH:2]>>[NH:1]C(=S)[NH:2]",
        "Replace a urea oxygen with sulfur.",
        "CNC(=O)NC",
        "CNC(=S)NC",
    ),
    _row(
        "urea_to_sulfamide",
        "Urea to sulfamide",
        "amide",
        "[NH:1]C(=O)[NH:2]>>[NH:1]S(=O)(=O)[NH:2]",
        "Replace a urea carbonyl with a sulfonyl.",
        "CNC(=O)NC",
        "CNS(=O)(=O)NC",
    ),
    # --- Whole-ring phenyl replacements. Monosubstituted, then para. ---
    _row(
        "phenyl_to_2_thienyl",
        "Phenyl to 2-thienyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cccs1",
        "Replace a monosubstituted phenyl with thiophen-2-yl.",
        "Cc1ccccc1",
        "Cc1cccs1",
    ),
    _row(
        "phenyl_to_3_thienyl",
        "Phenyl to 3-thienyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1ccsc1",
        "Replace a monosubstituted phenyl with thiophen-3-yl.",
        "Cc1ccccc1",
        "Cc1ccsc1",
    ),
    _row(
        "phenyl_to_2_furyl",
        "Phenyl to 2-furyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1ccco1",
        "Replace a monosubstituted phenyl with furan-2-yl.",
        "Cc1ccccc1",
        "Cc1ccco1",
    ),
    _row(
        "phenyl_to_3_furyl",
        "Phenyl to 3-furyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1ccoc1",
        "Replace a monosubstituted phenyl with furan-3-yl.",
        "Cc1ccccc1",
        "Cc1ccoc1",
    ),
    _row(
        "phenyl_to_2_pyrrolyl",
        "Phenyl to 2-pyrrolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1ccc[nH]1",
        "Replace a monosubstituted phenyl with 1H-pyrrol-2-yl.",
        "Cc1ccccc1",
        "Cc1ccc[nH]1",
    ),
    _row(
        "phenyl_to_3_pyrrolyl",
        "Phenyl to 3-pyrrolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cc[nH]c1",
        "Replace a monosubstituted phenyl with 1H-pyrrol-3-yl.",
        "Cc1ccccc1",
        "Cc1cc[nH]c1",
    ),
    _row(
        "phenyl_to_2_thiazolyl",
        "Phenyl to 2-thiazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1nccs1",
        "Replace a monosubstituted phenyl with thiazol-2-yl.",
        "Cc1ccccc1",
        "Cc1nccs1",
    ),
    _row(
        "phenyl_to_4_thiazolyl",
        "Phenyl to 4-thiazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cscn1",
        "Replace a monosubstituted phenyl with thiazol-4-yl.",
        "Cc1ccccc1",
        "Cc1cscn1",
    ),
    _row(
        "phenyl_to_5_thiazolyl",
        "Phenyl to 5-thiazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cncs1",
        "Replace a monosubstituted phenyl with thiazol-5-yl.",
        "Cc1ccccc1",
        "Cc1cncs1",
    ),
    _row(
        "phenyl_to_2_oxazolyl",
        "Phenyl to 2-oxazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1ncco1",
        "Replace a monosubstituted phenyl with oxazol-2-yl.",
        "Cc1ccccc1",
        "Cc1ncco1",
    ),
    _row(
        "phenyl_to_4_oxazolyl",
        "Phenyl to 4-oxazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cocn1",
        "Replace a monosubstituted phenyl with oxazol-4-yl.",
        "Cc1ccccc1",
        "Cc1cocn1",
    ),
    _row(
        "phenyl_to_5_oxazolyl",
        "Phenyl to 5-oxazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cnco1",
        "Replace a monosubstituted phenyl with oxazol-5-yl.",
        "Cc1ccccc1",
        "Cc1cnco1",
    ),
    _row(
        "phenyl_to_2_imidazolyl",
        "Phenyl to 2-imidazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1ncc[nH]1",
        "Replace a monosubstituted phenyl with 1H-imidazol-2-yl.",
        "Cc1ccccc1",
        "Cc1ncc[nH]1",
    ),
    _row(
        "phenyl_to_4_imidazolyl",
        "Phenyl to 4-imidazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1c[nH]cn1",
        "Replace a monosubstituted phenyl with 1H-imidazol-4-yl.",
        "Cc1ccccc1",
        "Cc1c[nH]cn1",
    ),
    _row(
        "phenyl_to_3_pyrazolyl",
        "Phenyl to 3-pyrazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cc[nH]n1",
        "Replace a monosubstituted phenyl with 1H-pyrazol-3-yl.",
        "Cc1ccccc1",
        "Cc1cc[nH]n1",
    ),
    _row(
        "phenyl_to_4_pyrazolyl",
        "Phenyl to 4-pyrazolyl",
        "phenyl",
        "[!#1:1]c1ccccc1>>[!#1:1]c1cn[nH]c1",
        "Replace a monosubstituted phenyl with 1H-pyrazol-4-yl.",
        "Cc1ccccc1",
        "Cc1cn[nH]c1",
    ),
    _row(
        "para_phenyl_to_25_thienyl",
        "Para-phenyl to 2,5-thienyl",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]c1ccc([!#1:2])s1",
        "Replace a para-disubstituted benzene with thiophene-2,5-diyl.",
        "Cc1ccc(C)cc1",
        "Cc1ccc(C)s1",
    ),
    _row(
        "para_phenyl_to_25_furyl",
        "Para-phenyl to 2,5-furyl",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]c1ccc([!#1:2])o1",
        "Replace a para-disubstituted benzene with furan-2,5-diyl.",
        "Cc1ccc(C)cc1",
        "Cc1ccc(C)o1",
    ),
    _row(
        "para_phenyl_to_25_pyrrolyl",
        "Para-phenyl to 2,5-pyrrolyl",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]c1ccc([!#1:2])[nH]1",
        "Replace a para-disubstituted benzene with 1H-pyrrole-2,5-diyl.",
        "Cc1ccc(C)cc1",
        "Cc1ccc(C)[nH]1",
    ),
    _row(
        "para_phenyl_to_thiazolyl",
        "Para-phenyl to thiazolyl",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]c1cnc([!#1:2])s1",
        "Replace a para-disubstituted benzene with a thiazole. p-Xylene gives Cc1cnc(C)s1.",
        "Cc1ccc(C)cc1",
        "Cc1cnc(C)s1",
    ),
    _row(
        "para_phenyl_to_oxazolyl",
        "Para-phenyl to oxazolyl",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]c1coc([!#1:2])n1",
        "Replace a para-disubstituted benzene with an oxazole. p-Xylene gives Cc1coc(C)n1.",
        "Cc1ccc(C)cc1",
        "Cc1coc(C)n1",
    ),
    _row(
        "para_phenyl_to_imidazolyl",
        "Para-phenyl to imidazolyl",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]c1nc([!#1:2])c[nH]1",
        "Replace a para-disubstituted benzene with an imidazole. p-Xylene gives Cc1c[nH]c(C)n1.",
        "Cc1ccc(C)cc1",
        "Cc1c[nH]c(C)n1",
    ),
    _row(
        "para_phenyl_to_35_pyrazolyl",
        "Para-phenyl to 3,5-pyrazolyl",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]c1cc([!#1:2])[nH]n1",
        "Replace a para-disubstituted benzene with 1H-pyrazole-3,5-diyl.",
        "Cc1ccc(C)cc1",
        "Cc1cc(C)[nH]n1",
    ),
    _row(
        "para_phenyl_to_bcp",
        "Para-phenyl to bicyclo[1.1.1]pentane",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]C12CC([!#1:2])(C1)C2",
        "Replace a para-disubstituted benzene with bicyclo[1.1.1]pentane-1,3-diyl.",
        "Cc1ccc(C)cc1",
        "CC12CC(C)(C1)C2",
    ),
    _row(
        "para_phenyl_to_cubane",
        "Para-phenyl to cubane",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]C12C3C4C1C5C2C3C45[!#1:2]",
        "Replace a para-disubstituted benzene with cubane-1,4-diyl.",
        "Cc1ccc(C)cc1",
        "CC12C3C4C1C1C2C3C41C",
    ),
    _row(
        "para_phenyl_to_222",
        "Para-phenyl to bicyclo[2.2.2]octane",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]C12CCC([!#1:2])(CC1)CC2",
        "Replace a para-disubstituted benzene with bicyclo[2.2.2]octane-1,4-diyl.",
        "Cc1ccc(C)cc1",
        "CC12CCC(C)(CC1)CC2",
    ),
    _row(
        "para_phenyl_to_cyclobutane",
        "Para-phenyl to 1,3-cyclobutane",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]C1CC([!#1:2])C1",
        "Replace a para-disubstituted benzene with cyclobutane-1,3-diyl. "
        "Cis and trans are not assigned.",
        "Cc1ccc(C)cc1",
        "CC1CC(C)C1",
    ),
    _row(
        "para_phenyl_to_cyclohexane",
        "Para-phenyl to 1,4-cyclohexane",
        "phenyl",
        "[!#1:1]c1ccc([!#1:2])cc1>>[!#1:1]C1CCC([!#1:2])CC1",
        "Saturate a para-disubstituted benzene to cyclohexane-1,4-diyl. "
        "Cis and trans are not assigned.",
        "Cc1ccc(O)cc1",
        "CC1CCC(O)CC1",
    ),
    _row(
        "benzene_to_cyclohexane",
        "Benzene to cyclohexane",
        "phenyl",
        "[c;R1:1]1[c;R1:2][c;R1:3][c;R1:4][c;R1:5][c;R1:6]1>>[C:1]1[C:2][C:3][C:4][C:5][C:6]1",
        "Saturate an isolated benzene ring to cyclohexane. Fused rings are skipped.",
        "Cc1ccccc1",
        "CC1CCCCC1",
    ),
    # --- Heteroatom swaps inside an existing ring. ---
    _row(
        "indole_to_benzofuran",
        "Indole to benzofuran",
        "ring_heteroatom",
        "[nH]1[c:1][c:2][c:3]2[c:4][c:5][c:6][c:7][c:8]12>>"
        "o1[c:1][c:2][c:3]2[c:4][c:5][c:6][c:7][c:8]12",
        "Replace the indole NH with oxygen.",
        "Cc1c[nH]c2ccccc12",
        "Cc1coc2ccccc12",
    ),
    _row(
        "indole_to_benzothiophene",
        "Indole to benzothiophene",
        "ring_heteroatom",
        "[nH]1[c:1][c:2][c:3]2[c:4][c:5][c:6][c:7][c:8]12>>"
        "s1[c:1][c:2][c:3]2[c:4][c:5][c:6][c:7][c:8]12",
        "Replace the indole NH with sulfur.",
        "Cc1c[nH]c2ccccc12",
        "Cc1csc2ccccc12",
    ),
    _row(
        "indole_to_indene",
        "Indole to indene",
        "ring_heteroatom",
        "[nH]1[c:1][c:2][c:3]2[c:4][c:5][c:6][c:7][c:8]12>>"
        "C1[c:1][c:2][c:3]2[c:4][c:5][c:6][c:7][c:8]12",
        "Replace the indole NH with a methylene.",
        "c1ccc2[nH]ccc2c1",
        "C1=Cc2ccccc2C1",
    ),
    _row(
        "pyrrole_to_furan",
        "Pyrrole to furan",
        "ring_heteroatom",
        "[c;R1:1]1[c;R1:2][c;R1:3][c;R1:4][nH;R1]1>>[c:1]1[c:2][c:3][c:4]o1",
        "Replace the NH of a monocyclic pyrrole with oxygen. Indoles are skipped.",
        "Cc1ccc[nH]1",
        "Cc1ccco1",
    ),
    _row(
        "pyrrole_to_thiophene",
        "Pyrrole to thiophene",
        "ring_heteroatom",
        "[c;R1:1]1[c;R1:2][c;R1:3][c;R1:4][nH;R1]1>>[c:1]1[c:2][c:3][c:4]s1",
        "Replace the NH of a monocyclic pyrrole with sulfur. Indoles are skipped.",
        "Cc1ccc[nH]1",
        "Cc1cccs1",
    ),
    _row(
        "imidazole_to_oxazole",
        "Imidazole to oxazole",
        "ring_heteroatom",
        "[c;R1:1]1[n;R1][c;R1:2][c;R1:3][nH;R1]1>>[c:1]1[n][c:2][c:3]o1",
        "Replace the NH of a monocyclic imidazole with oxygen.",
        "Cc1ncc[nH]1",
        "Cc1ncco1",
    ),
    _row(
        "imidazole_to_thiazole",
        "Imidazole to thiazole",
        "ring_heteroatom",
        "[c;R1:1]1[n;R1][c;R1:2][c;R1:3][nH;R1]1>>[c:1]1[n][c:2][c:3]s1",
        "Replace the NH of a monocyclic imidazole with sulfur.",
        "Cc1ncc[nH]1",
        "Cc1nccs1",
    ),
    _row(
        "imidazole_to_pyrazole",
        "Imidazole to pyrazole",
        "ring_heteroatom",
        "[c;R1:1]1[n;R1][c;R1:2][nH;R1][c;R1:3]1>>[c:1]1[n][nH][c:2][c:3]1",
        "Move the pyridine-like nitrogen of a monocyclic imidazole next to the NH.",
        "c1c[nH]cn1",
        "c1cn[nH]c1",
    ),
    _row(
        "benzimidazole_to_benzoxazole",
        "Benzimidazole to benzoxazole",
        "ring_heteroatom",
        "[nH]1[c:1][n][c:2]2[c:3][c:4][c:5][c:6][c:7]12>>"
        "o1[c:1][n][c:2]2[c:3][c:4][c:5][c:6][c:7]12",
        "Replace the benzimidazole NH with oxygen.",
        "c1ccc2[nH]cnc2c1",
        "c1ccc2ocnc2c1",
    ),
    _row(
        "benzimidazole_to_benzothiazole",
        "Benzimidazole to benzothiazole",
        "ring_heteroatom",
        "[nH]1[c:1][n][c:2]2[c:3][c:4][c:5][c:6][c:7]12>>"
        "s1[c:1][n][c:2]2[c:3][c:4][c:5][c:6][c:7]12",
        "Replace the benzimidazole NH with sulfur.",
        "c1ccc2[nH]cnc2c1",
        "c1ccc2scnc2c1",
    ),
    _row(
        "pyridine_to_piperidine",
        "Pyridine to piperidine",
        "ring_heteroatom",
        "[c;R1:1]1[c;R1:2][c;R1:3][n;R1][c;R1:4][c;R1:5]1>>[C:1]1[C:2][C:3]N[C:4][C:5]1",
        "Saturate an isolated pyridine to piperidine. Quinolines are skipped.",
        "c1ccncc1",
        "C1CCNCC1",
    ),
    _row(
        "pyridine_to_n_oxide",
        "Pyridine to N-oxide",
        "ring_heteroatom",
        "[n;H0;R:1]>>[n+:1][O-]",
        "Oxidize a ring nitrogen that has no hydrogen to the N-oxide.",
        "c1ccncc1",
        "[O-][n+]1ccccc1",
    ),
    # --- Saturated-ring heteroatom swaps. ---
    _row(
        "piperidine_to_morpholine",
        "Piperidine to morpholine",
        "saturated_ring",
        "[N:1]1[C:2][C:3][CH2][C:4][C:5]1>>[N:1]1[C:2][C:3]O[C:4][C:5]1",
        "Replace the 4-methylene of a piperidine with oxygen. "
        "A substituent already at the 4-position blocks the match.",
        "CN1CCCCC1",
        "CN1CCOCC1",
    ),
    _row(
        "morpholine_to_piperidine",
        "Morpholine to piperidine",
        "saturated_ring",
        "[N:1]1[C:2][C:3]O[C:4][C:5]1>>[N:1]1[C:2][C:3][CH2][C:4][C:5]1",
        "Replace the morpholine oxygen with a methylene.",
        "C1COCCN1",
        "C1CCNCC1",
    ),
    _row(
        "morpholine_to_thiomorpholine",
        "Morpholine to thiomorpholine",
        "saturated_ring",
        "[N:1]1[C:2][C:3]O[C:4][C:5]1>>[N:1]1[C:2][C:3]S[C:4][C:5]1",
        "Replace the morpholine oxygen with sulfur.",
        "C1COCCN1",
        "C1CSCCN1",
    ),
    _row(
        "piperazine_to_piperidine",
        "Piperazine to piperidine",
        "saturated_ring",
        "[N:1]1[C:2][C:3][NH][C:4][C:5]1>>[N:1]1[C:2][C:3][CH2][C:4][C:5]1",
        "Replace one piperazine NH with a methylene.",
        "C1CNCCN1",
        "C1CCNCC1",
    ),
    _row(
        "piperidine_to_piperazine",
        "Piperidine to piperazine",
        "saturated_ring",
        "[N:1]1[C:2][C:3][CH2][C:4][C:5]1>>[N:1]1[C:2][C:3][NH][C:4][C:5]1",
        "Replace the 4-methylene of a piperidine with NH.",
        "C1CCNCC1",
        "C1CNCCN1",
    ),
    _row(
        "morpholine_to_piperazine",
        "Morpholine to piperazine",
        "saturated_ring",
        "[N:1]1[C:2][C:3]O[C:4][C:5]1>>[N:1]1[C:2][C:3][NH][C:4][C:5]1",
        "Replace the morpholine oxygen with NH.",
        "C1COCCN1",
        "C1CNCCN1",
    ),
    _row(
        "piperazine_to_morpholine",
        "Piperazine to morpholine",
        "saturated_ring",
        "[N:1]1[C:2][C:3][NH][C:4][C:5]1>>[N:1]1[C:2][C:3]O[C:4][C:5]1",
        "Replace one piperazine NH with oxygen.",
        "C1CNCCN1",
        "C1COCCN1",
    ),
    _row(
        "tetrahydrofuran_to_pyrrolidine",
        "Tetrahydrofuran to pyrrolidine",
        "saturated_ring",
        "[O:1]1[C:2][C:3][C:4][C:5]1>>[NH:1]1[C:2][C:3][C:4][C:5]1",
        "Replace the oxygen of a tetrahydrofuran with NH.",
        "C1CCOC1",
        "C1CCNC1",
    ),
    _row(
        "pyrrolidine_to_tetrahydrofuran",
        "Pyrrolidine to tetrahydrofuran",
        "saturated_ring",
        "[NH:1]1[C:2][C:3][C:4][C:5]1>>[O:1]1[C:2][C:3][C:4][C:5]1",
        "Replace the NH of a pyrrolidine with oxygen.",
        "C1CCNC1",
        "C1CCOC1",
    ),
    # --- Acyclic and diaryl linkers. ---
    _row(
        "linker_o_to_ch2",
        "Dialkyl ether O to CH2",
        "linker",
        f"[{_LINKER_ATOM}:1][O;!R][{_LINKER_ATOM}:2]>>[#6:1]C[#6:2]",
        "Replace an acyclic ether oxygen between two non-methyl carbons with CH2. "
        "Esters and methoxy groups are not matched.",
        "c1ccc(OCc2ccccc2)cc1",
        "c1ccc(CCc2ccccc2)cc1",
    ),
    _row(
        "linker_o_to_nh",
        "Dialkyl ether O to NH",
        "linker",
        f"[{_LINKER_ATOM}:1][O;!R][{_LINKER_ATOM}:2]>>[#6:1]N[#6:2]",
        "Replace an acyclic ether oxygen between two non-methyl carbons with NH.",
        "c1ccc(OCc2ccccc2)cc1",
        "c1ccc(CNc2ccccc2)cc1",
    ),
    _row(
        "linker_o_to_s",
        "Dialkyl ether O to S",
        "linker",
        f"[{_LINKER_ATOM}:1][O;!R][{_LINKER_ATOM}:2]>>[#6:1]S[#6:2]",
        "Replace an acyclic ether oxygen between two non-methyl carbons with sulfur.",
        "c1ccc(OCc2ccccc2)cc1",
        "c1ccc(CSc2ccccc2)cc1",
    ),
    _row(
        "linker_ch2_to_o",
        "Linker CH2 to O",
        "linker",
        f"[{_LINKER_ATOM}:1][CH2;!R][{_LINKER_ATOM}:2]>>[#6:1]O[#6:2]",
        "Replace one acyclic methylene between two non-methyl carbons with oxygen.",
        "c1ccc(CCc2ccccc2)cc1",
        "c1ccc(COc2ccccc2)cc1",
    ),
    _row(
        "linker_nh_to_o",
        "Linker NH to O",
        "linker",
        f"[{_LINKER_ATOM}:1][NH;!R][{_LINKER_ATOM}:2]>>[#6:1]O[#6:2]",
        "Replace an acyclic NH linker between two non-methyl carbons with oxygen.",
        "c1ccc(NCc2ccccc2)cc1",
        "c1ccc(COc2ccccc2)cc1",
    ),
    _row(
        "linker_nh_to_ch2",
        "Linker NH to CH2",
        "linker",
        f"[{_LINKER_ATOM}:1][NH;!R][{_LINKER_ATOM}:2]>>[#6:1]C[#6:2]",
        "Replace an acyclic NH linker between two non-methyl carbons with CH2.",
        "c1ccc(NCc2ccccc2)cc1",
        "c1ccc(CCc2ccccc2)cc1",
    ),
    _row(
        "linker_s_to_o",
        "Linker S to O",
        "linker",
        f"[{_LINKER_ATOM}:1][S;!R][{_LINKER_ATOM}:2]>>[#6:1]O[#6:2]",
        "Replace an acyclic sulfide between two non-methyl carbons with oxygen.",
        "c1ccc(SCc2ccccc2)cc1",
        "c1ccc(COc2ccccc2)cc1",
    ),
    _row(
        "linker_s_to_ch2",
        "Linker S to CH2",
        "linker",
        f"[{_LINKER_ATOM}:1][S;!R][{_LINKER_ATOM}:2]>>[#6:1]C[#6:2]",
        "Replace an acyclic sulfide between two non-methyl carbons with CH2.",
        "c1ccc(SCc2ccccc2)cc1",
        "c1ccc(CCc2ccccc2)cc1",
    ),
    _row(
        "sulfide_to_sulfone",
        "Sulfide to sulfone",
        "linker",
        "[#6:1][SX2][#6:2]>>[#6:1]S(=O)(=O)[#6:2]",
        "Oxidize a sulfide between two carbons to the sulfone.",
        "CSCC",
        "CCS(C)(=O)=O",
    ),
    _row(
        "sulfone_to_ketone",
        "Sulfone to ketone",
        "linker",
        "[#6:1]S(=O)(=O)[#6:2]>>[#6:1]C(=O)[#6:2]",
        "Replace a sulfone between two carbons with a ketone.",
        "CS(=O)(=O)C",
        "CC(C)=O",
    ),
    _row(
        "ketone_to_sulfone",
        "Ketone to sulfone",
        "linker",
        "[#6:1][CX3](=O)[#6:2]>>[#6:1]S(=O)(=O)[#6:2]",
        "Replace a ketone between two carbons with a sulfone.",
        "CC(=O)C",
        "CS(C)(=O)=O",
    ),
    _row(
        "ketone_to_oxetane",
        "Ketone to 3,3-oxetane",
        "linker",
        "[#6:1][CX3](=O)[#6:2]>>[#6:1]C1([#6:2])COC1",
        "Replace a ketone with a 3,3-disubstituted oxetane.",
        "CC(=O)C",
        "CC1(C)COC1",
    ),
    _row(
        "ketone_to_ch2",
        "Diaryl ketone to methylene",
        "linker",
        "[c:1]C(=O)[c:2]>>[c:1]C[c:2]",
        "Replace a diaryl ketone with a methylene linker.",
        "O=C(c1ccccc1)c1ccccc1",
        "c1ccc(Cc2ccccc2)cc1",
    ),
    _row(
        "diaryl_ch2_to_o",
        "Diaryl methylene to ether",
        "linker",
        "[c:1][CH2][c:2]>>[c:1]O[c:2]",
        "Replace a diarylmethane linker with an ether.",
        "c1ccc(Cc2ccccc2)cc1",
        "c1ccc(Oc2ccccc2)cc1",
    ),
    _row(
        "diaryl_ch2_to_nh",
        "Diaryl methylene to NH",
        "linker",
        "[c:1][CH2][c:2]>>[c:1][NH][c:2]",
        "Replace a diarylmethane linker with NH.",
        "c1ccc(Cc2ccccc2)cc1",
        "c1ccc(Nc2ccccc2)cc1",
    ),
    _row(
        "diaryl_ch2_to_s",
        "Diaryl methylene to S",
        "linker",
        "[c:1][CH2][c:2]>>[c:1]S[c:2]",
        "Replace a diarylmethane linker with sulfur.",
        "c1ccc(Cc2ccccc2)cc1",
        "c1ccc(Sc2ccccc2)cc1",
    ),
    _row(
        "diaryl_ch2_to_ketone",
        "Diaryl methylene to ketone",
        "linker",
        "[c:1][CH2][c:2]>>[c:1]C(=O)[c:2]",
        "Replace a diarylmethane linker with a ketone.",
        "c1ccc(Cc2ccccc2)cc1",
        "O=C(c1ccccc1)c1ccccc1",
    ),
    _row(
        "diaryl_ch2_to_sulfone",
        "Diaryl methylene to sulfone",
        "linker",
        "[c:1][CH2][c:2]>>[c:1]S(=O)(=O)[c:2]",
        "Replace a diarylmethane linker with a sulfone.",
        "c1ccc(Cc2ccccc2)cc1",
        "O=S(=O)(c1ccccc1)c1ccccc1",
    ),
    _row(
        "diaryl_ethyl_to_ether",
        "Diaryl ethyl to ether",
        "linker",
        "[c:1][CH2][CH2][c:2]>>[c:1]O[c:2]",
        "Contract a 1,2-diarylethane to a diaryl ether.",
        "c1ccc(CCc2ccccc2)cc1",
        "c1ccc(Oc2ccccc2)cc1",
    ),
    _row(
        "diaryl_ethyl_to_cyclopropane",
        "Diaryl ethyl to cyclopropane",
        "linker",
        "[c:1][CH2][CH2][c:2]>>[c:1]C1CC1[c:2]",
        "Tie a 1,2-diarylethane into a 1,2-diarylcyclopropane. Cis and trans are not assigned.",
        "c1ccc(CCc2ccccc2)cc1",
        "c1ccc(C2CC2c2ccccc2)cc1",
    ),
    _row(
        "diaryl_ethyl_to_alkene",
        "Diaryl ethyl to alkene",
        "linker",
        "[c:1][CH2][CH2][c:2]>>[c:1]C=C[c:2]",
        "Oxidize a 1,2-diarylethane linker to a stilbene. E/Z is not assigned.",
        "c1ccc(CCc2ccccc2)cc1",
        "C(=Cc1ccccc1)c1ccccc1",
    ),
    _row(
        "diaryl_ethyl_to_alkyne",
        "Diaryl ethyl to alkyne",
        "linker",
        "[c:1][CH2][CH2][c:2]>>[c:1]C#C[c:2]",
        "Oxidize a 1,2-diarylethane linker to a diaryl alkyne.",
        "c1ccc(CCc2ccccc2)cc1",
        "C(#Cc1ccccc1)c1ccccc1",
    ),
    _row(
        "alkyne_to_para_phenyl",
        "Alkyne to para-phenyl",
        "linker",
        "[!#1:1]C#C[!#1:2]>>[!#1:1]c1ccc([!#1:2])cc1",
        "Replace an internal alkyne with a para-phenylene.",
        "CC#CC",
        "Cc1ccc(C)cc1",
    ),
    _row(
        "trans_alkene_to_amide",
        "Trans-alkene to amide",
        "linker",
        "[#6:1]/C=C/[#6:2]>>[#6:1]C(=O)N[#6:2]",
        "Replace a trans-disubstituted alkene with a secondary amide.",
        r"C/C=C/C",
        "CNC(C)=O",
    ),
    # --- Basic groups, nitro, phosphate. ---
    _row(
        "alkyl_amine_to_guanidine",
        "Alkyl NH2 to guanidine",
        "basic_polar",
        "[CX4:1][NH2]>>[CX4:1]NC(=N)N",
        "Replace an aliphatic primary amine with a guanidine.",
        "CCN",
        "CCNC(=N)N",
    ),
    _row(
        "alkyl_amine_to_amidine",
        "Alkyl CH2NH2 to amidine",
        "basic_polar",
        "[#6:1][CH2][NH2]>>[#6:1]C(=N)N",
        "Replace the carbon of an aliphatic primary aminomethyl with an amidine carbon.",
        "CCN",
        "CC(=N)N",
    ),
    _row(
        "aryl_nitro_to_cn",
        "Aryl nitro to CN",
        "basic_polar",
        "[c:1][N+](=O)[O-]>>[c:1]C#N",
        "Replace an aromatic nitro group with a nitrile.",
        "[O-][N+](=O)c1ccccc1",
        "N#Cc1ccccc1",
    ),
    _row(
        "phosphate_to_phosphonate",
        "Phosphate to phosphonate",
        "basic_polar",
        "[#6:1]OP(=O)(O)O>>[#6:1]CP(=O)(O)O",
        "Replace a phosphate ester oxygen with CH2, giving the phosphonate.",
        "CCOP(=O)(O)O",
        "CCCP(=O)(O)O",
    ),
    _row(
        "phosphonate_to_phosphate",
        "Phosphonate to phosphate",
        "basic_polar",
        "[#6:1]CP(=O)(O)O>>[#6:1]OP(=O)(O)O",
        "Replace the methylene of a phosphonate with oxygen, giving the phosphate.",
        "CCCP(=O)(O)O",
        "CCOP(=O)(O)O",
    ),
)

_BY_KEY: dict[str, Bioisostere] = {row.key: row for row in BIOISOSTERES}


def bioisostere_keys() -> tuple[str, ...]:
    """Stable keys in dictionary order."""
    return tuple(row.key for row in BIOISOSTERES)


def get_bioisostere(key: str) -> Bioisostere:
    """Return one transform. Raises ``KeyError`` when the key is unknown."""
    return _BY_KEY[key]


def bioisosteres_in(category: str) -> tuple[Bioisostere, ...]:
    """Transforms in one category, in dictionary order."""
    return tuple(row for row in BIOISOSTERES if row.category == category)


def iter_bioisosteres(keys: Iterable[str] | None = None) -> tuple[Bioisostere, ...]:
    """All transforms, or the named subset in the order requested."""
    if keys is None:
        return BIOISOSTERES
    return tuple(get_bioisostere(key) for key in keys)


def _reaction(smirks: str) -> Chem.rdChemReactions.ChemicalReaction:
    rxn = AllChem.ReactionFromSmarts(smirks)
    if rxn is None:
        raise ValueError(f"Could not parse bioisostere SMIRKS: {smirks}")
    if rxn.GetNumReactantTemplates() != 1 or rxn.GetNumProductTemplates() != 1:
        raise ValueError("A bioisostere SMIRKS needs one reactant and one product.")
    return rxn


def _as_mol(mol: Chem.Mol | str) -> Chem.Mol | None:
    if isinstance(mol, str):
        return Chem.MolFromSmiles(mol)
    return mol


def site_count(mol: Chem.Mol | str, transform: Bioisostere | str) -> int:
    """How many times the reactant pattern matches. Symmetric sites each count."""
    parsed = _as_mol(mol)
    if parsed is None:
        return 0
    row = transform if isinstance(transform, Bioisostere) else get_bioisostere(transform)
    # RunReactants counts each symmetric site. The reactant template does not,
    # because implicit hydrogens in ``[cH]`` are not a substructure match.
    return len(_reaction(row.smirks).RunReactants((parsed,)))


def apply_bioisostere(
    mol: Chem.Mol | str,
    transform: Bioisostere | str,
    *,
    atom_indices: Sequence[int] | None = None,
) -> tuple[str, ...]:
    """Unique product SMILES for one transform applied once at each match.

    The parent SMILES is omitted. Products that fail sanitization are dropped.
    Several sites become several products, not one product that changes every site.
    When *atom_indices* is set, a match is kept only when it contains one of those
    atoms, so a selected sketch region limits the replacement.
    """
    parsed = _as_mol(mol)
    if parsed is None:
        return ()
    row = transform if isinstance(transform, Bioisostere) else get_bioisostere(transform)
    try:
        work = Chem.Mol(parsed)
        Chem.SanitizeMol(work)
    except ValueError:
        return ()
    parent = Chem.MolToSmiles(work, isomericSmiles=True)
    reaction = _reaction(row.smirks)
    selected = None if atom_indices is None else {int(index) for index in atom_indices}
    matches = work.GetSubstructMatches(reaction.GetReactantTemplate(0))
    products = reaction.RunReactants((work,))
    if len(matches) != len(products):
        if selected is not None:
            return ()
        paired = ((None, item) for item in products)
    else:
        paired = zip(matches, products)
    seen: list[str] = []
    known: set[str] = set()
    for match, product_tuple in paired:
        if selected is not None and (match is None or not (set(match) & selected)):
            continue
        product = product_tuple[0]
        try:
            Chem.SanitizeMol(product)
        except ValueError:
            continue
        smiles = Chem.MolToSmiles(product, isomericSmiles=True)
        if not smiles or smiles == parent or smiles in known:
            continue
        known.add(smiles)
        seen.append(smiles)
    return tuple(seen)


def matching_bioisosteres(
    mol: Chem.Mol | str,
    atom_indices: Sequence[int],
) -> tuple[tuple[Bioisostere, tuple[str, ...]], ...]:
    """Transforms that change at least one selected atom, with their product SMILES."""
    found: list[tuple[Bioisostere, tuple[str, ...]]] = []
    for row in BIOISOSTERES:
        products = apply_bioisostere(mol, row, atom_indices=atom_indices)
        if products:
            found.append((row, products))
    return tuple(found)


def apply_bioisosteres(
    mol: Chem.Mol | str,
    transforms: Sequence[Bioisostere | str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """``(transform key, product SMILES)`` for each transform, parent omitted.

    The same product proposed by two transforms is kept twice, once under each key.
    """
    rows = (
        BIOISOSTERES
        if transforms is None
        else tuple(
            row if isinstance(row, Bioisostere) else get_bioisostere(row) for row in transforms
        )
    )
    out: list[tuple[str, str]] = []
    for row in rows:
        for smiles in apply_bioisostere(mol, row):
            out.append((row.key, smiles))
    return tuple(out)
