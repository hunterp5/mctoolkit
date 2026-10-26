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

"""IUPAC GR-2.2 / GR-2.3 contracted atom labels and common abbreviations."""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem


@dataclass(frozen=True)
class ContractedLabel:
    """A single-attachment contracted label (e.g. CF3, Ph, OMe)."""

    display: str  # canonical display text
    element: str  # attachment-atom element symbol
    smiles: str  # RDKit SMILES; first atom is the attachment point
    max_bonds: int = 1  # open valences used by the sketch attachment


# Keys are uppercase lookup forms (no spaces).
_CONTRACTED: dict[str, ContractedLabel] = {}


def _reg(display: str, element: str, smiles: str, *aliases: str, max_bonds: int = 1) -> None:
    lab = ContractedLabel(display=display, element=element, smiles=smiles, max_bonds=max_bonds)
    for key in (display, *aliases):
        _CONTRACTED[key.upper().replace(" ", "")] = lab


# --- Haloalkyl / fluoro ---
_reg("CF3", "C", "C(F)(F)F", "F3C")
_reg("CF2H", "C", "C(F)F", "F2HC", "CHF2")
_reg("CH2F", "C", "CF", "FCH2")
_reg("C2F5", "C", "C(F)(F)C(F)(F)F", "CF2CF3", "C2F5")
_reg("C3F7", "C", "C(F)(F)C(F)(F)C(F)(F)F", "CF2CF2CF3", "N-C3F7", "NC3F7")
_reg("SF5", "S", "S(F)(F)(F)(F)F", "SF5")
_reg("OCF3", "O", "OC(F)(F)F", "OCF3", "CF3O")
_reg("SCF3", "S", "SC(F)(F)F", "SCF3", "CF3S")

# --- Alkyl ---
_reg("CH3", "C", "C", "H3C")
_reg("Me", "C", "C", "ME")
_reg("Et", "C", "CC", "ET", "CH2CH3", "C2H5")
_reg("Pr", "C", "CCC", "PR", "NPR", "N-PR", "CH2CH2CH3")
_reg("nPr", "C", "CCC", "NPR")
_reg("iPr", "C", "C(C)C", "IPR", "ISPR", "CH(CH3)2")
_reg("nBu", "C", "CCCC", "NBU", "BU", "CH2CH2CH2CH3")
_reg("iBu", "C", "CC(C)C", "IBU", "ISBU", "CH2CH(CH3)2")
_reg("sBu", "C", "C(C)CC", "SBU", "SECBU", "CH(CH3)CH2CH3")
_reg("tBu", "C", "C(C)(C)C", "TBU", "C(CH3)3")
_reg("nPent", "C", "CCCCC", "NPENT", "PENTYL")
_reg("nHex", "C", "CCCCCC", "NHEX", "HEXYL")
_reg("Cy", "C", "C1CCCCC1", "CY", "CYCLOHEXYL", "C6H11")
_reg("cPr", "C", "C1CC1", "CPR", "CYCLOPROPYL")
_reg("cBu", "C", "C1CCC1", "CBU", "CYCLOBUTYL")
_reg("cPent", "C", "C1CCCC1", "CPENT", "CYCLOPENTYL")
_reg("Ad", "C", "C12CC3CC(CC(C3)C1)C2", "AD", "ADAMANTYL")
_reg("vinyl", "C", "C=C", "VINYL", "CH=CH2")
_reg("allyl", "C", "CC=C", "ALLYL", "CH2CH=CH2")
_reg("propargyl", "C", "CC#C", "PROPARGYL", "CH2CCH")

# --- Aryl / benzyl ---
_reg("Ph", "C", "c1ccccc1", "PH", "C6H5")
_reg("Bn", "C", "Cc1ccccc1", "BN", "CH2PH", "CH2C6H5", "Bzl")
_reg("Bz", "C", "C(=O)c1ccccc1", "BZ", "COPH")
_reg("Tol", "C", "c1ccc(C)cc1", "TOL", "P-TOL", "PTOL")
_reg("Mes", "C", "c1c(C)cc(C)cc1C", "MES", "MESITYL")
_reg("Naph", "C", "c1ccc2ccccc2c1", "NAPH", "NAPHTHYL", "1-NAPH")
_reg("PMB", "C", "Cc1ccc(OC)cc1", "PMB", "4-MEOC6H4CH2")
_reg("PMP", "C", "c1ccc(OC)cc1", "PMP", "4-MEOC6H4")

# --- Alkoxy / aryloxy / thio ---
_reg("OMe", "O", "OC", "OME", "OCH3")
_reg("OEt", "O", "OCC", "OET", "OCH2CH3")
_reg("OiPr", "O", "OC(C)C", "OIPR", "OCH(CH3)2")
_reg("OtBu", "O", "OC(C)(C)C", "OTBU", "OC(CH3)3")
_reg("OPh", "O", "Oc1ccccc1", "OPH", "OC6H5")
_reg("OBn", "O", "OCc1ccccc1", "OBN", "OBZL", "OCH2PH")
_reg("OAc", "O", "OC(=O)C", "OAC", "OCOCH3")
_reg("OBz", "O", "OC(=O)c1ccccc1", "OBZ")
_reg("OTs", "O", "OS(=O)(=O)c1ccc(C)cc1", "OTS")
_reg("OMs", "O", "OS(=O)(=O)C", "OMS")
_reg("OTf", "O", "OS(=O)(=O)C(F)(F)F", "OTF")
_reg("SMe", "S", "SC", "SME", "SCH3")
_reg("SEt", "S", "SCC", "SET")
_reg("SPh", "S", "Sc1ccccc1", "SPH")
_reg("SBn", "S", "SCc1ccccc1", "SBN")

# --- Carbonyls / acids / esters / amides ---
_reg("CN", "C", "C#N", "C≡N")
_reg("COOH", "C", "C(=O)O", "CO2H")
_reg("CHO", "C", "C=O")
_reg("Ac", "C", "C(=O)C", "AC", "COCH3")
_reg("Piv", "C", "C(=O)C(C)(C)C", "PIV", "COC(CH3)3")
_reg("CO2Me", "C", "C(=O)OC", "COOMe", "COOME", "COOCH3")
_reg("CO2Et", "C", "C(=O)OCC", "COOEt", "COOET", "COOCH2CH3")
_reg("CO2tBu", "C", "C(=O)OC(C)(C)C", "COOTBU", "COOtBu")
_reg("CONH2", "C", "C(=O)N", "CONH2")
_reg("CONMe2", "C", "C(=O)N(C)C", "CONME2")
_reg("COCl", "C", "C(=O)Cl", "COCL")

# --- Nitrogen ---
_reg("NO2", "N", "[N+](=O)[O-]", "NO2")
_reg("N3", "N", "N=[N+]=[N-]", "N3", "AZIDE")
_reg("NCO", "N", "N=C=O", "NCO")
_reg("NCS", "N", "N=C=S", "NCS")
_reg("NH2", "N", "N", "NH2")
_reg("NHMe", "N", "NC", "NHME")
_reg("NMe2", "N", "N(C)C", "NME2")
_reg("NEt2", "N", "N(CC)CC", "NET2")
_reg("NHAc", "N", "NC(=O)C", "NHAC")
_reg("NHBoc", "N", "NC(=O)OC(C)(C)C", "NHBOC")
_reg("NHCbz", "N", "NC(=O)OCc1ccccc1", "NHCBZ", "NHZ")
_reg("NHTs", "N", "NS(=O)(=O)c1ccc(C)cc1", "NHTS")
_reg("NBoc", "N", "N(C(=O)OC(C)(C)C)", "NBOC", max_bonds=2)
_reg("NPhth", "N", "N1C(=O)c2ccccc2C1=O", "NPHTH", "PHTH")

# --- Sulfur / phosphorus / boron / silicon ---
_reg("SO2", "S", "S(=O)=O", "SO2")
_reg("SO3H", "S", "S(=O)(=O)O", "SO3H")
_reg("SO2NH2", "S", "S(=O)(=O)N", "SO2NH2")
_reg("SO2Me", "S", "S(=O)(=O)C", "SO2ME", "MESO2")
_reg("SO2Ph", "S", "S(=O)(=O)c1ccccc1", "SO2PH")
_reg("Ts", "S", "S(=O)(=O)c1ccc(C)cc1", "TS", "TOS")
_reg("Ms", "S", "S(=O)(=O)C", "MS")
_reg("Tf", "S", "S(=O)(=O)C(F)(F)F", "TF", "SO2CF3")
_reg("PO3H2", "P", "P(=O)(O)O", "PO3H2")
_reg("PO(OEt)2", "P", "P(=O)(OCC)OCC", "POOET2", "P(O)(OET)2")
_reg("B(OH)2", "B", "B(O)O", "B(OH)2", "BOH2")
_reg("Bpin", "B", "B1OC(C)(C)C(C)(C)O1", "BPIN", "PINB")
_reg("TMS", "Si", "[Si](C)(C)C", "TMS", "SIME3", "SIME3")
_reg("TBS", "Si", "[Si](C)(C)C(C)(C)C", "TBS", "TBDMS")
_reg("TBDPS", "Si", "[Si](c1ccccc1)(c1ccccc1)C(C)(C)C", "TBDPS")
_reg("TIPS", "Si", "[Si](C(C)C)(C(C)C)C(C)C", "TIPS")
_reg("OTMS", "O", "O[Si](C)(C)C", "OTMS")
_reg("OTBS", "O", "O[Si](C)(C)C(C)(C)C", "OTBS", "OTBDMS")
_reg("OTIPS", "O", "O[Si](C(C)C)(C(C)C)C(C)C", "OTIPS")
_reg("SnBu3", "Sn", "[Sn](CCCC)(CCCC)CCCC", "SNBU3", "BU3SN")

# --- Protecting groups (C-attached) ---
_reg("Boc", "C", "C(=O)OC(C)(C)C", "BOC")
_reg("Cbz", "C", "C(=O)OCc1ccccc1", "CBZ", "Z")
_reg("Fmoc", "C", "C(=O)OCC1c2ccccc2-c2ccccc21", "FMOC")
_reg("Alloc", "C", "C(=O)OCC=C", "ALLOC")
_reg("MOM", "C", "COC", "MOM", "CH2OCH3")
_reg("MEM", "C", "COCCOC", "MEM")
_reg("SEM", "C", "COCC[Si](C)(C)C", "SEM")
_reg("THP", "C", "C1CCCCO1", "THP")
_reg("Tr", "C", "C(c1ccccc1)(c1ccccc1)c1ccccc1", "TR", "TRITYL", "CPh3")


# The terminal groups the Structure column contracts. The sketcher offers the same
# names, and only contracts an atom when the user picks one.
TABLE_CONTRACTED_LABELS: tuple[str, ...] = (
    "CF3",
    "CN",
    "N3",
    "CO2H",
    "SO3H",
    "PO3H2",
    "OMe",
    "Boc",
)


def lookup_contracted_label(raw: str) -> ContractedLabel | None:
    """Return a contracted label definition, or None if not recognized."""
    key = (raw or "").strip().upper().replace(" ", "").replace("≡", "#")
    if not key:
        return None
    return _CONTRACTED.get(key)


def parse_edit_atom_input(raw: str) -> tuple[str, list[str] | None, str | None] | None:
    """
    Parse Edit Atom text: element, wildcard, or contracted label.

    Returns ``(element, wildcard_els_or_None, abbrev_or_None)`` or None if invalid.
    """
    from .chem import _parse_atom_symbol_input

    s = (raw or "").strip()
    if not s:
        return None
    lab = lookup_contracted_label(s)
    if lab is not None:
        return (lab.element, None, lab.display)
    parsed = _parse_atom_symbol_input(s)
    if parsed is None:
        return None
    el, wels = parsed
    return (el, wels, None)


def contracted_max_bonds(abbrev: str | None) -> int | None:
    if not abbrev:
        return None
    lab = lookup_contracted_label(abbrev)
    return None if lab is None else int(lab.max_bonds)


def expand_contracted_label_on_atom(rw: Chem.RWMol, attach_idx: int, abbrev: str) -> bool:
    """
    Expand a contracted label onto an existing attachment atom in *rw*.

    The attachment atom must already exist at ``attach_idx`` and match the label's
    attachment element. Additional fragment atoms/bonds are added from the label SMILES.
    """
    lab = lookup_contracted_label(abbrev)
    if lab is None:
        return False
    frag = Chem.MolFromSmiles(lab.smiles)
    if frag is None or frag.GetNumAtoms() < 1:
        return False
    # Map fragment atom 0 → attach_idx; copy the rest (preserve aromaticity/charge/isotope).
    fmap: dict[int, int] = {0: int(attach_idx)}
    a0 = frag.GetAtomWithIdx(0)
    try:
        att = rw.GetAtomWithIdx(int(attach_idx))
        if a0.GetIsAromatic():
            att.SetIsAromatic(True)
        if a0.GetFormalCharge():
            att.SetFormalCharge(a0.GetFormalCharge())
    except Exception:
        pass
    for i in range(1, frag.GetNumAtoms()):
        a = frag.GetAtomWithIdx(i)
        na = Chem.Atom(a.GetAtomicNum())
        if a.GetFormalCharge():
            na.SetFormalCharge(a.GetFormalCharge())
        if a.GetIsotope():
            na.SetIsotope(a.GetIsotope())
        ni = rw.AddAtom(na)
        if a.GetIsAromatic():
            rw.GetAtomWithIdx(ni).SetIsAromatic(True)
        fmap[i] = ni
    for b in frag.GetBonds():
        a0i, a1i = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        i0, i1 = fmap[a0i], fmap[a1i]
        try:
            rw.AddBond(i0, i1, b.GetBondType())
            bobj = rw.GetBondBetweenAtoms(i0, i1)
            if bobj is not None and b.GetIsAromatic():
                bobj.SetIsAromatic(True)
        except Exception:
            pass
    return True
