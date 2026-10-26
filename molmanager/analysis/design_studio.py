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

"""Build one analog from a decomposed core and score it for the design studio.

R-group labels are the SMILES written by core-based decomposition (a dummy atom
at the attachment point). They zip onto the Core SMILES with RDKit's molzip.
The druglike score is a geometric-mean desirability on fast RDKit descriptors.
LogD, CNS MPO, and AB-MPS in the snapshot use the heuristic path (no Uni-pKa).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, QED

from molmanager.descriptors.medchem_descriptors import (
    ab_mps_score,
    cns_mpo_score,
    lipinski_violations,
    logd74_value,
    ro5_pass,
)

from .mpo_scoring import DesirabilitySpec, score_mpo_row

_RDKIT_ERRORS = (RuntimeError, ValueError, TypeError, OSError)
_BLANK = frozenset({"", "n/a", "na", "none", "null", "nan"})
_CORE_SUFFIX = re.compile(r"(?:^|_)Core$", re.IGNORECASE)
_RGROUP_PREFIX = re.compile(r"^(.*?)R\d+$", re.IGNORECASE)

# Gates are the usual oral-drug window: stay under MW 500 and 10 rotatable
# bonds, keep LogP and TPSA inside a band, and reward QED. Geometric mean
# means one property outside its gate pulls the whole score to zero.
DRUGLIKE_MPO_SPECS: tuple[DesirabilitySpec, ...] = (
    DesirabilitySpec("MW", "linear", "minimize", low=350.0, high=500.0),
    DesirabilitySpec("LogP", "linear", "target", low=0.0, high=5.0, target=2.5),
    DesirabilitySpec("TPSA", "linear", "target", low=20.0, high=140.0, target=75.0),
    DesirabilitySpec("QED", "linear", "maximize", low=0.3, high=0.7),
    DesirabilitySpec("RotBonds", "linear", "minimize", low=5.0, high=10.0),
)

_TERM_LABELS = {
    "MW": "MW",
    "LogP": "LogP",
    "TPSA": "TPSA",
    "QED": "QED",
    "RotBonds": "Rotatable bonds",
}


class DesignAssemblyError(ValueError):
    """The core and substituent labels could not be built into one molecule."""


@dataclass(frozen=True)
class DesignTerm:
    """One descriptor and, when it is in the druglike profile, its desirability."""

    key: str
    label: str
    value: float
    desirability: float | None


@dataclass(frozen=True)
class DesignSnapshot:
    """Fast descriptors and scores for the molecule currently on the canvas."""

    error: str | None = None
    terms: tuple[DesignTerm, ...] = ()
    mpo: float | None = None
    hbd: int | None = None
    hba: int | None = None
    ro5_pass: str | None = None
    ro5_violations: int | None = None
    logd: float | None = None
    cns_mpo: float | None = None
    ab_mps: float | None = None


def suggest_core_column(headers: Sequence[str], row_axis: str) -> str | None:
    """Return the decomposition Core column that belongs with *row_axis*.

    ``RGD_R1`` prefers ``RGD_Core``. A single ``*_Core`` column is used when
    the axis name does not carry that prefix.
    """
    axis = (row_axis or "").strip()
    match = _RGROUP_PREFIX.match(axis)
    if match:
        preferred = f"{match.group(1)}Core"
        for name in headers:
            if name.casefold() == preferred.casefold() and name != axis:
                return name
    matches = [
        name for name in headers if name != axis and _CORE_SUFFIX.search((name or "").strip())
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def series_core_from_labels(values: Sequence[str]) -> tuple[str | None, str]:
    """Return ``(smiles, state)`` for the cores of one SAR series.

    *state* is ``ok`` when every non-blank value is the same SMILES, ``missing``
    when none are filled, and ``conflict`` when the series has more than one core.
    """
    kept: list[str] = []
    for raw in values:
        text = (raw or "").strip()
        if text.casefold() in _BLANK:
            continue
        kept.append(text)
    if not kept:
        return None, "missing"
    if len(set(kept)) == 1:
        return kept[0], "ok"
    return None, "conflict"


def assemble_rgroup_product(core_smiles: str, pieces: Sequence[tuple[str, str]]) -> str:
    """Zip *core_smiles* with ``(axis name, substituent SMILES)`` pairs.

    Each piece must contain one dummy atom (``[*:1]``, ``[H][*:2]``, and so on),
    matching the labels core-based decomposition writes. Explicit hydrogens left
    by a hydrogen cap are removed. Raises :class:`DesignAssemblyError` with a
    message safe to show in the status bar.
    """
    core = _attachment_mol(core_smiles, axis="Core")
    frags = [_attachment_mol(smiles, axis=axis) for axis, smiles in pieces]
    try:
        combined = core
        for frag in frags:
            combined = Chem.CombineMols(combined, frag)
        zipped = Chem.molzip(combined)
        if zipped is None:
            raise DesignAssemblyError("Could not attach those substituents to the core.")
        Chem.SanitizeMol(zipped)
        zipped = Chem.RemoveHs(zipped)
        smiles = Chem.MolToSmiles(zipped, canonical=True) or ""
    except DesignAssemblyError:
        raise
    except _RDKIT_ERRORS as exc:
        raise DesignAssemblyError("Could not attach those substituents to the core.") from exc
    if not smiles:
        raise DesignAssemblyError("Could not attach those substituents to the core.")
    return smiles


def compute_design_snapshot(mol: Chem.Mol | None) -> DesignSnapshot:
    """Score *mol* with RDKit descriptors and the druglike desirability profile.

    Ionization-backed fields use the heuristic fallback (``states=[]``), so this
    stays on the UI thread. A later Uni-pKa job can replace LogD, CNS MPO, and
    AB-MPS.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return DesignSnapshot(error="empty")
    try:
        safe = Chem.Mol(mol)
        Chem.SanitizeMol(safe)
    except _RDKIT_ERRORS:
        return DesignSnapshot(error="invalid")
    try:
        values = {
            "MW": float(Descriptors.MolWt(safe)),
            "LogP": float(Crippen.MolLogP(safe)),
            "TPSA": float(Descriptors.TPSA(safe)),
            "QED": float(QED.qed(safe)),
            "RotBonds": float(Lipinski.NumRotatableBonds(safe)),
        }
        overall, parts = score_mpo_row(values, list(DRUGLIKE_MPO_SPECS), method="geometric")
        terms = tuple(
            DesignTerm(
                key=key,
                label=_TERM_LABELS[key],
                value=float(values[key]),
                desirability=parts.get(key),
            )
            for key in _TERM_LABELS
        )
        return DesignSnapshot(
            terms=terms,
            mpo=overall,
            hbd=int(Lipinski.NumHDonors(safe)),
            hba=int(Lipinski.NumHAcceptors(safe)),
            ro5_pass=ro5_pass(safe),
            ro5_violations=int(lipinski_violations(safe)),
            logd=float(logd74_value(safe, [])),
            cns_mpo=float(cns_mpo_score(safe, [])),
            ab_mps=float(ab_mps_score(safe, [])),
        )
    except _RDKIT_ERRORS:
        return DesignSnapshot(error="invalid")


def _attachment_mol(smiles: str, *, axis: str) -> Chem.Mol:
    text = (smiles or "").strip()
    if not text or text.casefold() in _BLANK:
        raise DesignAssemblyError(f"{axis} is empty, so this analog cannot be built.")
    mol = Chem.MolFromSmiles(text)
    if mol is None or not any(atom.GetAtomicNum() == 0 for atom in mol.GetAtoms()):
        raise DesignAssemblyError(f"{axis} is not an R-group SMILES with an attachment point (*).")
    return mol
