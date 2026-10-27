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
from statistics import fmean

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, QED

from molmanager.descriptors.medchem_descriptors import (
    ab_mps_score,
    cns_mpo_score,
    lipinski_violations,
    logd74_value,
    ro5_pass,
)

from .activity_cliff_analysis import change_heavy_atom_count, fragment_tanimoto_distance
from .mmp_analysis import MmpPair, aggregate_transforms, apply_transform_summary_to_mol
from .mpo_scoring import DesirabilitySpec, score_mpo_row
from .sali_analysis import sali_index

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

_CLIFF_HEAVY_ATOMS = 4
_CLIFF_ABS_DELTA = 1.0
_SUGGESTION_LIMIT = 8

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


@dataclass(frozen=True)
class SeriesRow:
    """One decomposed table row a suggestion can swap a substituent on."""

    core_smiles: str
    substituents: tuple[tuple[str, str], ...]
    activity: float | None
    product_smiles: str = ""


@dataclass(frozen=True)
class DesignSuggestion:
    """One analog the design list can hold."""

    smiles: str
    title: str
    detail: str
    source: str


def mmp_suggestions(
    mol: Chem.Mol | None,
    pairs: Sequence[MmpPair],
    *,
    limit: int = _SUGGESTION_LIMIT,
) -> list[DesignSuggestion]:
    """Transforms from *pairs* that apply to *mol*, best median activity gain first.

    A suggestion is marked as a cliff when the change is small and the median
    activity shift is large. SALI uses that median and the fragment similarity.
    """
    if mol is None or not pairs:
        return []
    seed = _canonical_smiles(mol)
    if not seed:
        return []
    ranked = [
        summary
        for summary in aggregate_transforms(pairs)
        if summary.median_delta > 0.0 and summary.n > 0
    ]
    ranked.sort(key=lambda summary: (summary.median_delta, summary.n), reverse=True)
    found: list[DesignSuggestion] = []
    seen = {seed}
    for summary in ranked:
        if len(found) >= limit:
            break
        try:
            products = apply_transform_summary_to_mol(mol, summary)
        except _RDKIT_ERRORS:
            continue
        product = next((smiles for smiles in products if _canonical_text(smiles) not in seen), "")
        if not product:
            continue
        canon = _canonical_text(product)
        seen.add(canon)
        found.append(_mmp_suggestion(summary, canon))
    return found


def rgroup_swap_suggestions(
    current_smiles: str,
    rows: Sequence[SeriesRow],
    *,
    limit: int = _SUGGESTION_LIMIT,
) -> list[DesignSuggestion]:
    """One-position substituent swaps away from *current_smiles* on a shared core.

    The activity estimate is the reference row's activity plus the difference
    between the mean activity of the new substituent and the one it replaces.
    """
    seed = _canonical_text(current_smiles)
    if not seed or not rows:
        return []
    prepared = [_PreparedRow.from_series(row) for row in rows]
    prepared = [row for row in prepared if row is not None and row.product]
    if not prepared:
        return []
    reference = next((row for row in prepared if row.product == seed), None)
    if reference is None:
        return []
    known = {row.product for row in prepared}
    found: list[tuple[float, DesignSuggestion]] = []
    for axis, old_label in reference.substituents:
        others = []
        for row in prepared:
            label = row.label_at(axis)
            if label and label != old_label and label not in others:
                others.append(label)
        mean_old = _mean_activity(prepared, axis, old_label)
        for new_label in others:
            mean_new = _mean_activity(prepared, axis, new_label)
            if mean_old is None or mean_new is None:
                continue
            swapped = tuple(
                (name, new_label if name == axis else label)
                for name, label in reference.substituents
            )
            try:
                product = assemble_rgroup_product(reference.core_smiles, swapped)
            except DesignAssemblyError:
                continue
            canon = _canonical_text(product)
            if not canon or canon in known:
                continue
            shift = mean_new - mean_old
            predicted = reference.activity + shift if reference.activity is not None else mean_new
            known.add(canon)
            found.append(
                (
                    predicted,
                    DesignSuggestion(
                        smiles=canon,
                        title=f"{axis}: {_short(old_label)} → {_short(new_label)}",
                        detail=_rgroup_detail(predicted, shift, canon),
                        source="rgroup",
                    ),
                )
            )
    found.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in found[:limit]]


def _mmp_suggestion(summary, smiles: str) -> DesignSuggestion:
    heavy = change_heavy_atom_count(summary.sidechain_from, summary.sidechain_to)
    distance = fragment_tanimoto_distance(summary.sidechain_from, summary.sidechain_to)
    similarity = max(0.0, min(1.0, 1.0 - distance))
    sali = sali_index(abs(summary.median_delta), similarity)
    cliff = heavy <= _CLIFF_HEAVY_ATOMS and abs(summary.median_delta) >= _CLIFF_ABS_DELTA
    sign = "+" if summary.median_delta >= 0 else ""
    bits = [
        f"MMP median Δ {sign}{summary.median_delta:.2f}",
        f"n={summary.n}",
        f"SALI {sali:.1f}",
    ]
    if cliff:
        bits.append("activity cliff")
    note = suggestion_mpo_note(smiles)
    if note:
        bits.append(note)
    title = f"{_short(summary.sidechain_from)} → {_short(summary.sidechain_to)}"
    return DesignSuggestion(
        smiles=smiles,
        title=title,
        detail=" · ".join(bits),
        source="mmp",
    )


def _rgroup_detail(predicted: float, shift: float, smiles: str) -> str:
    sign = "+" if shift >= 0 else ""
    text = f"Series estimate {predicted:.2f} ({sign}{shift:.2f})"
    note = suggestion_mpo_note(smiles)
    if note:
        return f"{text} · {note}"
    return text


def suggestion_mpo_note(smiles: str) -> str:
    """Druglike MPO for a suggestion, or an empty string when it cannot be scored."""
    snapshot = compute_design_snapshot(_canonical_mol_text(smiles))
    if snapshot.mpo is None:
        return ""
    return f"MPO {snapshot.mpo:.2f}"


class _PreparedRow:
    def __init__(self, core_smiles: str, substituents, activity, product: str) -> None:
        self.core_smiles = core_smiles
        self.substituents = substituents
        self.activity = activity
        self.product = product

    @classmethod
    def from_series(cls, row: SeriesRow) -> _PreparedRow | None:
        core = (row.core_smiles or "").strip()
        if not core or core.casefold() in _BLANK:
            return None
        labels = tuple(
            (axis, label)
            for axis, label in row.substituents
            if (label or "").strip() and (label or "").strip().casefold() not in _BLANK
        )
        if not labels:
            return None
        product = _canonical_text(row.product_smiles)
        if not product:
            try:
                product = _canonical_text(assemble_rgroup_product(core, labels))
            except DesignAssemblyError:
                return None
        if not product:
            return None
        return cls(core, labels, row.activity, product)

    def label_at(self, axis: str) -> str:
        for name, label in self.substituents:
            if name == axis:
                return label
        return ""


def _mean_activity(rows: Sequence[_PreparedRow], axis: str, label: str) -> float | None:
    values = [
        row.activity for row in rows if row.label_at(axis) == label and row.activity is not None
    ]
    if not values:
        return None
    return float(fmean(values))


def _short(text: str, limit: int = 28) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[: limit - 1] + "…"


def _canonical_smiles(mol: Chem.Mol | None) -> str:
    if mol is None:
        return ""
    try:
        return Chem.MolToSmiles(Chem.Mol(mol), canonical=True) or ""
    except _RDKIT_ERRORS:
        return ""


def _canonical_text(smiles: str) -> str:
    text = (smiles or "").strip()
    if not text:
        return ""
    mol = Chem.MolFromSmiles(text)
    return _canonical_smiles(mol)


def _canonical_mol_text(smiles: str) -> Chem.Mol | None:
    text = _canonical_text(smiles)
    if not text:
        return None
    return Chem.MolFromSmiles(text)


def _attachment_mol(smiles: str, *, axis: str) -> Chem.Mol:
    text = (smiles or "").strip()
    if not text or text.casefold() in _BLANK:
        raise DesignAssemblyError(f"{axis} is empty, so this analog cannot be built.")
    mol = Chem.MolFromSmiles(text)
    if mol is None or not any(atom.GetAtomicNum() == 0 for atom in mol.GetAtoms()):
        raise DesignAssemblyError(f"{axis} is not an R-group SMILES with an attachment point (*).")
    return mol
