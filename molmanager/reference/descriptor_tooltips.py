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

"""Short Calculate Descriptors checkbox tooltips (what each property is)."""

from __future__ import annotations

from ..chem.rdkit_fingerprints import FpKind, spec_for_internal_key

_3D_NEED = " Needs 3D coordinates (confs or a 3D import); otherwise N/A."

_TOOLTIPS: dict[str, str] = {
    "FractionCSP3": "Fraction of carbon atoms that are sp3 (tetrahedral).",
    "LabuteASA": "Labute approximate surface area from 2D connectivity (not 3D SASA).",
    "LOGD74": "Predicted octanol–water distribution coefficient at pH 7.4.",
    "MolLogP": "Wildman–Crippen octanol–water partition coefficient (log P).",
    "LOGS_ESOL": "Intrinsic aqueous solubility (log S) from Delaney's ESOL model.",
    "LOGS74": "Predicted aqueous solubility (log S) at pH 7.4.",
    "MolWt": "Average molecular weight, including implicit hydrogens.",
    "MolMR": "Wildman–Crippen molar refractivity (polarizability-related size).",
    "TPSA": "Topological polar surface area from polar atom contributions.",
    "SMILES": "Canonical SMILES of the target structure.",
    "INCHIKEY": "InChIKey hashed identifier of the target structure.",
    "MOLFORMULA": "Hill-system molecular formula.",
    "QED": "Quantitative Estimate of Drug-likeness (0–1; higher is more drug-like).",
    "AB_MPS": (
        "AbbVie MPS: |log D7.4 − 3| + aromatic rings + rotatable bonds (lower is more favorable)."
    ),
    "RO5_VIOLATIONS": "Number of Lipinski Rule of Five property violations.",
    "RO5_PASS": "True when the structure has no Lipinski Rule of Five violations.",
    "CNS_MPO": "Wager CNS multiparameter score (0–6; higher is more CNS-like).",
    "HeavyAtomCount": "Number of non-hydrogen atoms.",
    "NumNHOH": "Count of nitrogen and oxygen atoms that carry at least one hydrogen.",
    "NumNO": "Count of nitrogen plus oxygen atoms.",
    "NumHeteroatoms": "Count of non-carbon, non-hydrogen atoms.",
    "NumHDonors": "Hydrogen-bond donor count (N–H and O–H).",
    "NumHAcceptors": "Hydrogen-bond acceptor count (typically N and O).",
    "NumRotatableBonds": "Number of non-ring single bonds that can rotate.",
    "NumValenceElectrons": "Total valence electrons in the molecule.",
    "RingCount": "Smallest-set-of-smallest-rings (SSSR) ring count.",
    "NumAromaticRings": "Number of aromatic rings.",
    "NumSaturatedRings": "Number of fully saturated rings.",
    "NumAliphaticRings": "Number of non-aromatic rings.",
    "NumSpiroAtoms": "Atoms shared by two rings at a single atom (spiro centers).",
    "NumBridgeheadAtoms": "Atoms that belong to three or more fused rings (bridgeheads).",
    "BertzCT": "Bertz topological complexity (branching and heteroatom content).",
    "BalabanJ": "Balaban J index (distance-based topological index).",
    "HallKierAlpha": "Hall–Kier alpha (unsaturation and heteroatom size).",
    "Kappa1": "Kier kappa1 shape index (how linear the molecule is).",
    "Kappa2": "Kier kappa2 shape index (branching / spatial density).",
    "NET_FORMAL_CHARGE": "Sum of formal charges on all atoms.",
    "MaxPartialCharge": "Most positive Gasteiger partial charge.",
    "MinPartialCharge": "Most negative Gasteiger partial charge.",
    "MaxAbsPartialCharge": "Largest absolute Gasteiger partial charge.",
    "MinAbsPartialCharge": "Smallest absolute Gasteiger partial charge.",
    "PMI1": "Smallest principal moment of inertia." + _3D_NEED,
    "PMI2": "Intermediate principal moment of inertia." + _3D_NEED,
    "PMI3": "Largest principal moment of inertia." + _3D_NEED,
    "NPR1": "Normalized PMI ratio I1/I3 (rod-like vs spherical)." + _3D_NEED,
    "NPR2": "Normalized PMI ratio I2/I3 (disc-like vs spherical)." + _3D_NEED,
    "Asphericity": "Deviation from a spherical shape (0 = sphere)." + _3D_NEED,
    "Eccentricity": "Shape eccentricity from the inertia tensor." + _3D_NEED,
    "InertialShapeFactor": "Inertial shape factor from the principal moments." + _3D_NEED,
    "RadiusOfGyration": "Mass-weighted RMS distance from the centroid." + _3D_NEED,
    "SpherocityIndex": "How spherical the 3D shape is (1 = sphere)." + _3D_NEED,
    "PBF": "Average atom distance to the plane of best fit." + _3D_NEED,
    "SASA": "Shrake–Rupley solvent-accessible surface area." + _3D_NEED,
    "MolVolume": "Van der Waals molecular volume." + _3D_NEED,
}

_ELEMENT_NAMES = {
    "C": "carbon",
    "N": "nitrogen",
    "O": "oxygen",
    "F": "fluorine",
    "Cl": "chlorine",
    "Br": "bromine",
    "I": "iodine",
    "S": "sulfur",
    "P": "phosphorus",
}


def _fingerprint_tooltip(internal_key: str) -> str | None:
    spec = spec_for_internal_key(internal_key)
    if spec is None:
        return None
    n = spec.n_bits
    r = spec.radius
    match spec.kind:
        case FpKind.MORGAN_BIT:
            return (
                f"On-bit count of a Morgan (ECFP-like) circular fingerprint (radius {r}, {n} bits)."
            )
        case FpKind.MORGAN_FCFP:
            return (
                f"On-bit count of a feature-based Morgan (FCFP) fingerprint (radius {r}, {n} bits)."
            )
        case FpKind.MORGAN_COUNT:
            return f"Hashed Morgan substructure occurrence count (radius {r}, {n} bins)."
        case FpKind.RDK_BIT:
            return f"On-bit count of an RDKit topological path fingerprint ({n} bits)."
        case FpKind.RDK_UNFOLDED_COUNT:
            return "Count of distinct RDKit paths with no bit folding."
        case FpKind.MACCS:
            return "On-bit count of the 166-key MACCS structural fingerprint."
        case FpKind.ATOM_PAIR_BIT:
            return f"On-bit count of a hashed atom-pair fingerprint ({n} bits)."
        case FpKind.ATOM_PAIR_COUNT:
            return f"Hashed atom-pair occurrence count ({n} bins)."
        case FpKind.TOPO_TORSION_BIT:
            return f"On-bit count of a hashed topological-torsion fingerprint ({n} bits)."
        case FpKind.TOPO_TORSION_COUNT:
            return f"Hashed topological-torsion occurrence count ({n} bins)."
        case FpKind.PATTERN:
            return "On-bit count of RDKit's pattern fingerprint (substructure-oriented)."
        case FpKind.LAYERED:
            return "On-bit count of RDKit's layered fingerprint."
        case FpKind.AVALON:
            return f"On-bit count of an Avalon chemical fingerprint ({n} bits)."
        case FpKind.PHARM2D_GOBBI:
            return "On-bit count of a Gobbi 2D pharmacophore fingerprint."
    return "On-bit count of this molecular fingerprint."


def descriptor_checkbox_tooltip(internal_key: str) -> str:
    """Plain-text hover help for a Calculate Descriptors checkbox."""
    key = (internal_key or "").strip()
    if not key:
        return ""
    text = _TOOLTIPS.get(key)
    if text:
        return text
    if key.startswith("Count_"):
        symbol = key.split("_", 1)[1]
        name = _ELEMENT_NAMES.get(symbol, symbol)
        return f"Number of {name} atoms."
    fp = _fingerprint_tooltip(key)
    if fp:
        return fp
    return ""
