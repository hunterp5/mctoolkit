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

"""Optional structure-preparation edits used by the Preparation Menu.

Each flag is independent. When several are on, they run in an order that keeps
each one meaningful: standardize, largest organic fragment, neutralize,
canonical tautomer, isotope labels, then explicit hydrogens. Add and remove
hydrogens only show or hide valence hydrogens. They do not change formal charge.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem

from .fragment_disconnect import collect_fragment_mols
from .molecule_conversion import mol_to_canonical_smiles
from .structure_hydrogens import add_explicit_hydrogens, remove_explicit_hydrogens
from .structure_neutralize import neutralize_mol

_PREP_ERRORS = (
    ValueError,
    TypeError,
    RuntimeError,
    ArithmeticError,
    AttributeError,
    KeyError,
    IndexError,
)

# RDKit's default tautomer search applies 1000 transforms and kekulizes every
# candidate. On a few thousand drugs that takes about a minute, and the
# molecules that hit the cap already return a truncated tautomer. 100 keeps
# that same result for ordinary structures and cuts the long tail.
_MAX_TAUTOMERS = 100
_MAX_TRANSFORMS = 100
_TAUTOMER_ENUMERATOR = None


@dataclass(frozen=True)
class StructurePrepareOptions:
    """Which molecule edits Prepare should apply. All default off."""

    standardize: bool = False
    largest_fragment: bool = False
    neutralize: bool = False
    canonical_tautomer: bool = False
    remove_isotopes: bool = False
    explicit_hydrogens: str = ""

    def has_edits(self) -> bool:
        """True when at least one molecule-changing box is on."""
        return bool(
            self.standardize
            or self.largest_fragment
            or self.neutralize
            or self.canonical_tautomer
            or self.remove_isotopes
            or self.explicit_hydrogens
        )

    def before_protonation(self) -> StructurePrepareOptions:
        """Edits that belong before a dominant-protomer step."""
        return StructurePrepareOptions(
            standardize=self.standardize,
            largest_fragment=self.largest_fragment,
        )

    def after_protonation(self) -> StructurePrepareOptions:
        """Edits that belong after the charge model."""
        return StructurePrepareOptions(
            canonical_tautomer=self.canonical_tautomer,
            remove_isotopes=self.remove_isotopes,
            explicit_hydrogens=self.explicit_hydrogens,
        )


def options_from_prepare_params(params: dict) -> StructurePrepareOptions | None:
    """Build options from a Prepare recording.

    A Fast Prepare recording that has none of the new flags returns ``None`` so
    the worker keeps the old largest-fragment behavior.
    """
    if not any(
        key in params
        for key in ("standardize", "largest_fragment", "canonical_tautomer", "explicit_hydrogens")
    ):
        return None
    hydrogens = str(params.get("explicit_hydrogens") or "")
    if hydrogens not in {"add", "remove"}:
        hydrogens = ""
    return StructurePrepareOptions(
        standardize=bool(params.get("standardize")),
        largest_fragment=bool(params.get("largest_fragment")),
        neutralize=bool(params.get("neutralize")) and not bool(params.get("protonate")),
        canonical_tautomer=bool(params.get("canonical_tautomer")),
        remove_isotopes=bool(params.get("remove_isotopes")),
        explicit_hydrogens=hydrogens,
    )


def apply_structure_prepare(
    mol,
    options: StructurePrepareOptions,
    source_text: str | None = None,
) -> tuple[object | None, str]:
    """Return ``(prepared mol, other-fragment SMILES)``.

    ``other-fragment SMILES`` is empty when the largest-fragment option is off
    or the structure has one piece.
    """
    if mol is None:
        return None, ""
    try:
        current = Chem.Mol(mol)
    except _PREP_ERRORS:
        return None, ""
    if options.standardize:
        current = _or_keep(current, _standardize)
    fragments = ""
    if options.largest_fragment:
        parent, fragments = _largest_organic_fragment(current, source_text)
        if parent is None:
            return None, ""
        current = parent
    if options.neutralize:
        current = neutralize_mol(current) or current
    if options.canonical_tautomer:
        current = _or_keep(current, _canonical_tautomer)
    if options.remove_isotopes:
        current = _or_keep(current, _remove_isotope_labels)
    if options.explicit_hydrogens == "add":
        current = add_explicit_hydrogens(current) or current
    elif options.explicit_hydrogens == "remove":
        current = remove_explicit_hydrogens(current) or current
    return current, fragments


def _or_keep(mol, step):
    try:
        updated = step(mol)
    except _PREP_ERRORS:
        return mol
    return mol if updated is None else updated


def _standardize(mol):
    from rdkit.Chem.MolStandardize import rdMolStandardize

    return rdMolStandardize.Cleanup(Chem.Mol(mol))


def _tautomer_enumerator():
    """Return one enumerator for this process.

    Constructing it compiles the tautomer rules, so a Prepare batch must not
    build a new one for every row.
    """
    global _TAUTOMER_ENUMERATOR
    if _TAUTOMER_ENUMERATOR is not None:
        return _TAUTOMER_ENUMERATOR
    from rdkit.Chem.MolStandardize import rdMolStandardize

    params = rdMolStandardize.CleanupParameters()
    params.maxTautomers = _MAX_TAUTOMERS
    params.maxTransforms = _MAX_TRANSFORMS
    _TAUTOMER_ENUMERATOR = rdMolStandardize.TautomerEnumerator(params)
    return _TAUTOMER_ENUMERATOR


def _canonical_tautomer(mol):
    return _tautomer_enumerator().Canonicalize(Chem.Mol(mol))


def _remove_isotope_labels(mol):
    editable = Chem.RWMol(Chem.Mol(mol))
    for atom in editable.GetAtoms():
        if atom.GetIsotope():
            atom.SetIsotope(0)
    return editable.GetMol()


def _largest_organic_fragment(mol, source_text: str | None) -> tuple[object | None, str]:
    """Keep the organic parent. Other components are canonical SMILES."""
    from rdkit.Chem.MolStandardize import rdMolStandardize

    pieces = collect_fragment_mols(mol, source_text)
    if not pieces:
        return None, ""
    if len(pieces) == 1:
        return pieces[0], ""
    combined = pieces[0]
    for piece in pieces[1:]:
        combined = Chem.CombineMols(combined, piece)
    parent = rdMolStandardize.LargestFragmentChooser(preferOrganic=True).choose(combined)
    if parent is None:
        return None, ""
    parent_smiles = mol_to_canonical_smiles(parent)
    rest: list[str] = []
    skipped_parent = False
    for piece in pieces:
        smiles = mol_to_canonical_smiles(piece)
        if not skipped_parent and smiles == parent_smiles:
            skipped_parent = True
            continue
        if smiles:
            rest.append(smiles)
    return parent, " . ".join(rest)
