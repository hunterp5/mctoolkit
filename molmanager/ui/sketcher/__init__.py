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
Chemical sketcher UI split across ``constants``, ``bonds``, ``wildcards``, ``chem``, ``sketch_graph``,
``sketch_rdkit``, ``toolbar_glyphs``, ``widget``, and ``dialog``.

Public imports match the former ``MolManager.ui.sketcher`` module path.

**Stereochemistry:** single-bond wedge/hash encode tetrahedral configuration (narrow end = stereocenter).
Alkene **E/Z** is inferred from 2D geometry in ``alkene_stereo``. Tautomers, atropisomers, and arbitrary
diastereomer sets are not auto-enumerated; see ``docs/STEREO_AND_ISOMERISM.md``.

**Depiction:** the canvas paints the same scene as the Structure column. Clean Up uses that
column's generated layout (no cell-fit rotation). Bond drags and the chain tool snap to a 30° grid.

**Bonds & valence:** internal bond ``order`` is 1–3 (single/double/triple); valence warnings sum incident
orders vs element/charge caps. Aromatic rings are Kekulized on load so doubles are preserved; see ``docs/VALENCE_BONDS_AND_AROMATICITY.md``.
"""

from .constants import (
    CLIPBOARD_PREFIX,
    DEFAULT_WILDCARD_ELEMENTS,
    SKETCH_ELEMENT_SYMBOLS,
    SKETCH_RING_TEMPLATES,
    TOOLBAR_ELEMENT_GROUPS,
    TOOLBAR_ELEMENT_SYMBOLS,
    WILDCARD_ELEMENT,
    WILDCARD_ELEMENT_CHOICES,
)
from .dialog import SketcherDialog
from .widget import SketchWidget

__all__ = [
    "CLIPBOARD_PREFIX",
    "DEFAULT_WILDCARD_ELEMENTS",
    "SKETCH_ELEMENT_SYMBOLS",
    "SKETCH_RING_TEMPLATES",
    "SketcherDialog",
    "SketchWidget",
    "TOOLBAR_ELEMENT_GROUPS",
    "TOOLBAR_ELEMENT_SYMBOLS",
    "WILDCARD_ELEMENT",
    "WILDCARD_ELEMENT_CHOICES",
]
