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

"""RDKit 2D structure rendering for the compound table (no Qt)."""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D

from ..table.structure_depiction_layout import (
    REACTION_DEPICT_PADDING,
    STRUCTURE_DEPICT_BOND_LINE_WIDTH,
    STRUCTURE_DEPICT_PADDING,
    structure_depict_width,
)

from .depiction_scene import SceneHighlight

# Bond length of RDKit's own 2D layouts, used when a molecule has no coordinates yet.
_RDKIT_BOND_LENGTH = 1.5


@dataclass(frozen=True)
class ReactionDrawSpec:
    """Render-2D payload for a reaction SMARTS / SMIRKS string."""

    smarts: str


def structure_cairo_dimensions(target_w: int, target_h: int) -> tuple[int, int]:
    """Return (width, height) for MolDraw2DCairo (same as the display target)."""
    return int(target_w), int(target_h)


def configure_mol_drawer(drawer: rdMolDraw2D.MolDraw2D, target_w: int) -> None:
    """Thinner bonds at table resolution; scale stroke with zoomed (2×) depictions."""
    opts = drawer.drawOptions()
    base_w = max(1.0, float(structure_depict_width()))
    ratio = max(1.0, float(target_w) / base_w)
    opts.bondLineWidth = float(STRUCTURE_DEPICT_BOND_LINE_WIDTH) * ratio
    opts.padding = float(STRUCTURE_DEPICT_PADDING)


def _apply_table_draw_options(drawer: rdMolDraw2D.MolDraw2DCairo, target_w: int) -> None:
    configure_mol_drawer(drawer, target_w)


def render_molecule_png(
    mol: Chem.Mol,
    target_w: int,
    target_h: int,
    *,
    highlight: SceneHighlight | None = None,
) -> bytes:
    """Draw *mol* to PNG bytes at the requested table / zoom size, with an optional *highlight*."""
    cw, ch = structure_cairo_dimensions(target_w, target_h)
    drawer = rdMolDraw2D.MolDraw2DCairo(int(cw), int(ch))
    configure_mol_drawer(drawer, int(cw))
    if highlight is None or not (highlight.atoms or highlight.bonds):
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    else:
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol, **_rdkit_highlight_args(mol, highlight))
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def _rdkit_highlight_args(mol: Chem.Mol, highlight: SceneHighlight) -> dict:
    """*highlight* as PrepareAndDrawMolecule keywords; radii become molecule units."""
    bond_length = _mean_bond_length(mol)
    bond_colours: dict[int, tuple[float, float, float]] = {}
    for (begin, end), colour in highlight.bonds.items():
        bond = mol.GetBondBetweenAtoms(int(begin), int(end))
        if bond is not None:
            bond_colours[bond.GetIdx()] = colour
    atoms = [atom for atom in highlight.atoms if 0 <= atom < mol.GetNumAtoms()]
    return {
        "highlightAtoms": atoms,
        "highlightAtomColors": {atom: highlight.atoms[atom] for atom in atoms},
        "highlightAtomRadii": {atom: highlight.radius(atom) * bond_length for atom in atoms},
        "highlightBonds": list(bond_colours),
        "highlightBondColors": bond_colours,
    }


def _mean_bond_length(mol: Chem.Mol) -> float:
    """Mean 2D bond length of *mol*'s coordinates, or RDKit's layout length without any."""
    if mol.GetNumConformers() == 0 or mol.GetNumBonds() == 0:
        return _RDKIT_BOND_LENGTH
    conformer = mol.GetConformer()
    lengths = [
        (
            conformer.GetAtomPosition(bond.GetBeginAtomIdx())
            - conformer.GetAtomPosition(bond.GetEndAtomIdx())
        ).Length()
        for bond in mol.GetBonds()
    ]
    mean = sum(lengths) / len(lengths)
    return mean if mean > 1e-6 else _RDKIT_BOND_LENGTH


def render_reaction_png(smarts: str, target_w: int, target_h: int) -> bytes:
    """Draw a reaction SMARTS scheme (reactants → products) to PNG bytes."""
    text = (smarts or "").strip()
    if not text:
        raise ValueError("Reaction SMARTS is empty.")
    rxn = AllChem.ReactionFromSmarts(text)
    if rxn is None:
        raise ValueError("Could not parse reaction SMARTS.")
    try:
        AllChem.SanitizeRxn(rxn)
    except Exception:
        pass
    try:
        AllChem.Compute2DCoordsForReaction(rxn)
    except Exception:
        pass
    cw, ch = structure_cairo_dimensions(target_w, target_h)
    drawer = rdMolDraw2D.MolDraw2DCairo(int(cw), int(ch))
    # Scale bonds like a molecule cell, not the wider reaction canvas.
    configure_mol_drawer(drawer, structure_depict_width())
    drawer.drawOptions().padding = float(REACTION_DEPICT_PADDING)
    drawer.DrawReaction(rxn, highlightByReactant=False)
    drawer.FinishDrawing()
    png = drawer.GetDrawingText()
    if not png:
        raise ValueError("Reaction depiction produced no image.")
    return png


def render_depict_payload_png(
    payload: Chem.Mol | ReactionDrawSpec, target_w: int, target_h: int
) -> bytes:
    """Draw a molecule or reaction payload to PNG bytes."""
    if isinstance(payload, ReactionDrawSpec):
        return render_reaction_png(payload.smarts, target_w, target_h)
    return render_molecule_png(payload, target_w, target_h)
