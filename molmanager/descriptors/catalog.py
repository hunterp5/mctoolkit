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

"""Display label → worker key for Calculate Descriptors tabs (no Qt)."""

from __future__ import annotations

from ..chem.rdkit_fingerprints import descriptor_fingerprint_categories
from .descriptors_3d import DESCRIPTOR_3D_ITEMS

# Tab titles in the Calculate Descriptors dialog (left to right).
DESCRIPTOR_TAB_ORDER: tuple[str, ...] = (
    "Physiochemical",
    "3D",
    "Fingerprints",
    "Name",
    "Drug-likeness",
    "Structural Counts",
    "Ring Counts",
    "Atom Counts",
    "Complexity",
    "Electronic",
)

# Static tabs: ordered (display label, internal worker key). Fingerprints and 3D are filled
# from their own registries so a new fingerprint spec or 3D descriptor cannot drift.
DESCRIPTOR_TAB_ITEMS: dict[str, tuple[tuple[str, str], ...]] = {
    "Physiochemical": (
        ("Fraction CSP3", "FractionCSP3"),
        ("Labute ASA", "LabuteASA"),
        ("LogD 7.4", "LOGD74"),
        ("LogP", "MolLogP"),
        ("LogS intrinsic (ESOL)", "LOGS_ESOL"),
        ("LogS 7.4", "LOGS74"),
        ("Mol Weight", "MolWt"),
        ("Molar Refractivity", "MolMR"),
        ("TPSA", "TPSA"),
    ),
    "Name": (
        ("SMILES String", "SMILES"),
        ("InChI Key", "INCHIKEY"),
        ("Molecular formula", "MOLFORMULA"),
    ),
    "Drug-likeness": (
        ("AB-MPS score", "AB_MPS"),
        ("BBB Score", "BBB_SCORE"),
        ("CNS MPO score", "CNS_MPO"),
        ("QED Score", "QED"),
        ("Ro5 pass", "RO5_PASS"),
        ("Ro5 violations", "RO5_VIOLATIONS"),
    ),
    "Structural Counts": (
        ("H-Bond Acceptors", "NumHAcceptors"),
        ("H-Bond Donors", "NumHDonors"),
        ("Heavy Atoms", "HeavyAtomCount"),
        ("Heteroatoms", "NumHeteroatoms"),
        ("NH/OH Count", "NumNHOH"),
        ("NO Count", "NumNO"),
        ("Rotatable Bonds", "NumRotatableBonds"),
        ("Valence Electrons", "NumValenceElectrons"),
    ),
    "Ring Counts": (
        ("Aliphatic Rings", "NumAliphaticRings"),
        ("Aromatic Rings", "NumAromaticRings"),
        ("Bridgehead Atoms", "NumBridgeheadAtoms"),
        ("Saturated Rings", "NumSaturatedRings"),
        ("Spiro Atoms", "NumSpiroAtoms"),
        ("Total Rings", "RingCount"),
    ),
    "Atom Counts": (
        ("Bromines", "Count_Br"),
        ("Carbons", "Count_C"),
        ("Chlorines", "Count_Cl"),
        ("Fluorines", "Count_F"),
        ("Iodines", "Count_I"),
        ("Nitrogens", "Count_N"),
        ("Oxygens", "Count_O"),
        ("Phosphorus", "Count_P"),
        ("Sulfurs", "Count_S"),
    ),
    "Complexity": (
        ("Balaban J", "BalabanJ"),
        ("Bertz Complexity", "BertzCT"),
        ("Hall-Kier Alpha", "HallKierAlpha"),
        ("Kappa 1", "Kappa1"),
        ("Kappa 2", "Kappa2"),
    ),
    "Electronic": (
        ("Max Abs Partial Charge", "MaxAbsPartialCharge"),
        ("Max Partial Charge", "MaxPartialCharge"),
        ("Min Abs Partial Charge", "MinAbsPartialCharge"),
        ("Min Partial Charge", "MinPartialCharge"),
        ("Net Formal Charge", "NET_FORMAL_CHARGE"),
    ),
}


def descriptor_tab_items(tab: str) -> tuple[tuple[str, str], ...]:
    """Ordered (display, internal) pairs for one Calculate Descriptors tab."""
    if tab == "3D":
        return DESCRIPTOR_3D_ITEMS
    if tab == "Fingerprints":
        return tuple(descriptor_fingerprint_categories().items())
    return DESCRIPTOR_TAB_ITEMS[tab]


def iter_descriptor_tab_items() -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Every tab in dialog order, with its items (empty tabs omitted)."""
    out: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for tab in DESCRIPTOR_TAB_ORDER:
        items = descriptor_tab_items(tab)
        if items:
            out.append((tab, items))
    return tuple(out)
