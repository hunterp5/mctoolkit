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

"""
Canonical RDKit molecular fingerprint registry for similarity, clustering, and descriptors.

Used by Fingerprint Similarity, Cluster, dimensionality reduction, QSAR, and Calculate Descriptors.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors, rdmolops

try:
    from rdkit.Chem.Pharm2D import Generate as Pharm2DGenerate
    from rdkit.Chem.Pharm2D import Gobbi_Pharm2D
except ImportError:  # pragma: no cover
    Pharm2DGenerate = None  # type: ignore[misc, assignment]
    Gobbi_Pharm2D = None  # type: ignore[misc, assignment]

_AVALON_AVAILABLE: bool | None = None


def avalon_fingerprints_available() -> bool:
    global _AVALON_AVAILABLE
    if _AVALON_AVAILABLE is None:
        try:
            from rdkit.Avalon import pyAvalonTools  # noqa: F401

            _AVALON_AVAILABLE = True
        except ImportError:
            _AVALON_AVAILABLE = False
    return _AVALON_AVAILABLE


class FpKind(str, Enum):
    MORGAN_BIT = "morgan_bit"
    MORGAN_FCFP = "morgan_fcfp"
    MORGAN_COUNT = "morgan_count"
    RDK_BIT = "rdk_bit"
    RDK_UNFOLDED_COUNT = "rdk_unfolded_count"
    MACCS = "maccs"
    ATOM_PAIR_BIT = "atom_pair_bit"
    ATOM_PAIR_COUNT = "atom_pair_count"
    TOPO_TORSION_BIT = "topo_torsion_bit"
    TOPO_TORSION_COUNT = "topo_torsion_count"
    PATTERN = "pattern"
    LAYERED = "layered"
    AVALON = "avalon"
    PHARM2D_GOBBI = "pharm2d_gobbi"


@dataclass(frozen=True)
class FingerprintSpec:
    """One fingerprint type exposed in tool UIs."""

    label: str
    internal_key: str
    kind: FpKind
    radius: int = 2
    n_bits: int = 2048
    max_path: int = 5
    similarity: bool = True


def _rdk_fingerprint_bitvect(mol: Chem.Mol, *, max_path: int = 5, fp_size: int = 2048):
    getter = getattr(AllChem, "GetRDKFingerprint", None)
    if getter is not None:
        return getter(mol, maxPath=max_path, fpSize=fp_size)
    return rdmolops.RDKFingerprint(mol, minPath=1, maxPath=max_path, fpSize=fp_size)


def _fingerprint_onbits(fp: Any) -> int:
    if fp is None:
        return 0
    if hasattr(fp, "GetNumOnBits"):
        return int(fp.GetNumOnBits())
    if hasattr(fp, "GetNonzeroElements"):
        return len(fp.GetNonzeroElements())
    return 0


def _compute_fingerprint(mol: Chem.Mol, spec: FingerprintSpec) -> Any | None:
    try:
        match spec.kind:
            case FpKind.MORGAN_BIT:
                return AllChem.GetMorganFingerprintAsBitVect(
                    mol, spec.radius, nBits=spec.n_bits, useFeatures=False
                )
            case FpKind.MORGAN_FCFP:
                return AllChem.GetMorganFingerprintAsBitVect(
                    mol, spec.radius, nBits=spec.n_bits, useFeatures=True
                )
            case FpKind.MORGAN_COUNT:
                return AllChem.GetHashedMorganFingerprint(mol, spec.radius, nBits=spec.n_bits)
            case FpKind.RDK_BIT:
                return _rdk_fingerprint_bitvect(mol, max_path=spec.max_path, fp_size=spec.n_bits)
            case FpKind.RDK_UNFOLDED_COUNT:
                return AllChem.UnfoldedRDKFingerprintCountBased(mol)
            case FpKind.MACCS:
                return rdMolDescriptors.GetMACCSKeysFingerprint(mol)
            case FpKind.ATOM_PAIR_BIT:
                return AllChem.GetHashedAtomPairFingerprintAsBitVect(mol, nBits=spec.n_bits)
            case FpKind.ATOM_PAIR_COUNT:
                return AllChem.GetHashedAtomPairFingerprint(mol, nBits=spec.n_bits)
            case FpKind.TOPO_TORSION_BIT:
                return AllChem.GetHashedTopologicalTorsionFingerprintAsBitVect(
                    mol, nBits=spec.n_bits
                )
            case FpKind.TOPO_TORSION_COUNT:
                return AllChem.GetHashedTopologicalTorsionFingerprint(mol, nBits=spec.n_bits)
            case FpKind.PATTERN:
                return AllChem.PatternFingerprint(mol)
            case FpKind.LAYERED:
                return AllChem.LayeredFingerprint(mol)
            case FpKind.AVALON:
                if not avalon_fingerprints_available():
                    return None
                from rdkit.Avalon import pyAvalonTools

                return pyAvalonTools.GetAvalonFP(mol, nBits=spec.n_bits)
            case FpKind.PHARM2D_GOBBI:
                if Pharm2DGenerate is None or Gobbi_Pharm2D is None:
                    return None
                return Pharm2DGenerate.Gen2DFingerprint(mol, Gobbi_Pharm2D.factory)
    except Exception:
        return None
    return None


def _build_fingerprint_specs() -> tuple[FingerprintSpec, ...]:
    specs: list[FingerprintSpec] = []
    for radius, n_bits, key_suffix in (
        (1, 1024, "1_1024"),
        (2, 1024, "2_1024"),
        (3, 1024, "3_1024"),
        (2, 2048, "2_2048"),
        (3, 2048, "3_2048"),
    ):
        specs.append(
            FingerprintSpec(
                label=f"Morgan (r={radius}, n={n_bits})",
                internal_key=f"FP_Morgan_{key_suffix}",
                kind=FpKind.MORGAN_BIT,
                radius=radius,
                n_bits=n_bits,
            )
        )
    for radius, n_bits in ((2, 1024), (3, 1024), (2, 2048), (3, 2048)):
        specs.append(
            FingerprintSpec(
                label=f"FCFP Morgan (r={radius}, n={n_bits})",
                internal_key=f"FP_FCFP_{radius}_{n_bits}",
                kind=FpKind.MORGAN_FCFP,
                radius=radius,
                n_bits=n_bits,
            )
        )
    for n_bits, key_suffix in ((1024, "1024"), (2048, "2048")):
        specs.append(
            FingerprintSpec(
                label=f"Morgan count (hashed, r=2, n={n_bits})",
                internal_key=f"FP_MorganCount_2_{key_suffix}",
                kind=FpKind.MORGAN_COUNT,
                radius=2,
                n_bits=n_bits,
            )
        )
    for n_bits, key_suffix in ((1024, "1024"), (2048, "2048"), (4096, "4096")):
        specs.append(
            FingerprintSpec(
                label=f"RDK path ({n_bits})",
                internal_key=f"FP_RDK_{key_suffix}",
                kind=FpKind.RDK_BIT,
                n_bits=n_bits,
            )
        )
    specs.append(
        FingerprintSpec(
            label="RDK path (unfolded count)",
            internal_key="FP_RDK_unfolded",
            kind=FpKind.RDK_UNFOLDED_COUNT,
        )
    )
    specs.append(
        FingerprintSpec(
            label="MACCS (166)",
            internal_key="FP_MACCS_166",
            kind=FpKind.MACCS,
            n_bits=166,
        )
    )
    for n_bits in (1024, 2048):
        specs.append(
            FingerprintSpec(
                label=f"Atom pair (hashed, {n_bits} bits)",
                internal_key=f"FP_AtomPair_{n_bits}",
                kind=FpKind.ATOM_PAIR_BIT,
                n_bits=n_bits,
            )
        )
    specs.append(
        FingerprintSpec(
            label="Atom pair (hashed count, 2048)",
            internal_key="FP_AtomPairCount_2048",
            kind=FpKind.ATOM_PAIR_COUNT,
            n_bits=2048,
        )
    )
    for n_bits in (1024, 2048):
        specs.append(
            FingerprintSpec(
                label=f"Topological torsion (hashed, {n_bits} bits)",
                internal_key=f"FP_TopoTorsion_{n_bits}",
                kind=FpKind.TOPO_TORSION_BIT,
                n_bits=n_bits,
            )
        )
    specs.append(
        FingerprintSpec(
            label="Topological torsion (hashed count, 2048)",
            internal_key="FP_TopoTorsionCount_2048",
            kind=FpKind.TOPO_TORSION_COUNT,
            n_bits=2048,
        )
    )
    specs.append(
        FingerprintSpec(
            label="Pattern fingerprint",
            internal_key="FP_Pattern",
            kind=FpKind.PATTERN,
        )
    )
    specs.append(
        FingerprintSpec(
            label="Layered fingerprint",
            internal_key="FP_Layered",
            kind=FpKind.LAYERED,
        )
    )
    if avalon_fingerprints_available():
        for n_bits in (512, 1024, 2048):
            specs.append(
                FingerprintSpec(
                    label=f"Avalon ({n_bits})",
                    internal_key=f"FP_Avalon_{n_bits}",
                    kind=FpKind.AVALON,
                    n_bits=n_bits,
                )
            )
    specs.append(
        FingerprintSpec(
            label="2D pharmacophore (Gobbi)",
            internal_key="FP_Pharm2D_Gobbi",
            kind=FpKind.PHARM2D_GOBBI,
        )
    )
    return tuple(specs)


FINGERPRINT_SPECS: tuple[FingerprintSpec, ...] = _build_fingerprint_specs()

# Legacy UI labels still accepted by :func:`fingerprint_for_label`.
LABEL_ALIASES: dict[str, str] = {
    "RDK (2048)": "RDK path (2048)",
    "Morgan (r=2, n=1024)": "Morgan (r=2, n=1024)",
    "Atom pair (hashed, 2048 bits)": "Atom pair (hashed, 2048 bits)",
    "Topological torsion (hashed, 2048 bits)": "Topological torsion (hashed, 2048 bits)",
}

_LABEL_TO_SPEC: dict[str, FingerprintSpec] = {s.label: s for s in FINGERPRINT_SPECS}
_KEY_TO_SPEC: dict[str, FingerprintSpec] = {s.internal_key: s for s in FINGERPRINT_SPECS}

SIMILARITY_FP_TYPE_LABELS: list[str] = [s.label for s in FINGERPRINT_SPECS if s.similarity]


def resolve_fingerprint_label(label: str) -> str:
    raw = (label or "").strip()
    return LABEL_ALIASES.get(raw, raw)


def spec_for_label(label: str) -> FingerprintSpec | None:
    return _LABEL_TO_SPEC.get(resolve_fingerprint_label(label))


def spec_for_internal_key(internal_key: str) -> FingerprintSpec | None:
    return _KEY_TO_SPEC.get(internal_key)


def fingerprint_is_gil_heavy(label: str) -> bool:
    """True when fingerprint generation often blocks the GIL (e.g. Gobbi Pharm2D)."""
    spec = spec_for_label(label)
    return spec is not None and spec.kind == FpKind.PHARM2D_GOBBI


def fingerprint_internal_key_is_gil_bound(internal_key: str) -> bool:
    """True when descriptor fingerprint columns should use the process pool (RDKit holds the GIL)."""
    spec = spec_for_internal_key(internal_key)
    if spec is None:
        return False
    return spec.kind != FpKind.MACCS


def int_fns_include_fingerprints(int_fns) -> bool:
    return any(isinstance(f, str) and f.startswith("FP_") for f in int_fns)


def fingerprint_for_label(mol: Chem.Mol, label: str) -> Any | None:
    spec = spec_for_label(label)
    if spec is None:
        return None
    return _compute_fingerprint(mol, spec)


def fingerprint_bitvect_for_ui_choice(mol: Chem.Mol, fp_choice: str) -> Any | None:
    """Fingerprint object suitable for :mod:`rdkit.DataStructs` similarity."""
    return fingerprint_for_label(mol, fp_choice)


def fingerprint_bitvect_for_row(
    oid: int,
    mol: Chem.Mol | None,
    fp_choice: str,
) -> Any | None:
    """
    Return a fingerprint bit vector for a table row, reusing the session cache when possible.

    Tools that only have a molecule (no OID) should call :func:`fingerprint_bitvect_for_ui_choice`.
    """
    if mol is None:
        return None
    spec = spec_for_label(fp_choice)
    if spec is not None:
        from .fingerprint_cache import get, store_from_mol

        cached = get(int(oid), spec.internal_key)
        if cached is not None:
            return cached
        return store_from_mol(int(oid), spec.internal_key, mol)
    return fingerprint_for_label(mol, fp_choice)


def fingerprint_onbits_for_internal_key(internal_key: str) -> Callable[[Chem.Mol], int | str]:
    spec = spec_for_internal_key(internal_key)

    def _calc(mol: Chem.Mol) -> int | str:
        if spec is None:
            return "N/A"
        fp = _compute_fingerprint(mol, spec)
        if fp is None:
            return "N/A"
        return _fingerprint_onbits(fp)

    return _calc


def descriptor_fingerprint_categories() -> dict[str, str]:
    """Display name → internal key for Calculate Descriptors → Fingerprints tab."""
    return {spec.label: spec.internal_key for spec in FINGERPRINT_SPECS}


def descriptor_onbits_column_name(fp_label: str) -> str:
    """Table column header for fingerprint on-bit counts from Calculate Descriptors."""
    return resolve_fingerprint_label(fp_label)


def descriptor_onbits_column_aliases(fp_label: str) -> tuple[str, ...]:
    """Current header, then the older ``… on-bits`` header from saved sessions."""
    label = descriptor_onbits_column_name(fp_label)
    return (label, f"{label} on-bits")


def fingerprint_onbits_for_descriptor(
    internal_key: str,
    oid: int | None,
) -> Callable[[Chem.Mol], int | str]:
    """Like :func:`fingerprint_onbits_for_internal_key` but caches the bit vector for reuse."""
    base = fingerprint_onbits_for_internal_key(internal_key)

    def _calc(mol: Chem.Mol) -> int | str:
        if oid is not None and mol is not None:
            from .fingerprint_cache import get, store_from_mol

            cached = get(int(oid), internal_key)
            if cached is not None:
                return _fingerprint_onbits(cached)
            fp = store_from_mol(int(oid), internal_key, mol)
            if fp is not None:
                return _fingerprint_onbits(fp)
        return base(mol)

    return _calc
