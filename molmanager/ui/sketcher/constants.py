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

"""Sketcher shared constants: elements, clipboard prefix, ring templates, geometry scale."""

from rdkit.Chem.rdchem import BondDir

# Wedge/hash in mol blocks: RDKit uses BEGINDASH for hash; some versions also expose BEGINHASH.
BOND_DIR_HASH = getattr(BondDir, "BEGINHASH", BondDir.BEGINDASH)

CLIPBOARD_PREFIX = "MOLMANAGER_SKETCHCLIP:v1:"

WILDCARD_ELEMENT = "*"
DEFAULT_WILDCARD_ELEMENTS = ["C", "N", "O"]

SKETCH_ELEMENT_SYMBOLS: tuple[str, ...] = (
    "H",
    "D",
    "T",
    "C",
    "N",
    "O",
    "F",
    "P",
    "S",
    "Cl",
    "Br",
    "I",
    "B",
    "Si",
    "Se",
    "Li",
    "Na",
    "K",
    "Rb",
    "Cs",
    "Mg",
    "Ca",
    "Sr",
    "Ba",
    "Al",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Mo",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "Sn",
    "Sb",
    "Te",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Gd",
    "Lu",
    "Eu",
    "Sm",
)

WILDCARD_ELEMENT_CHOICES = SKETCH_ELEMENT_SYMBOLS

ELEMENT_UPPER_MAP: dict[str, str] = {s.upper(): s for s in SKETCH_ELEMENT_SYMBOLS}

# Full informal PT families for every sketchable symbol (customize + left-panel grouping).
ELEMENT_FAMILY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hydrogen Isotopes", ("H", "D", "T")),
    ("Alkali Metals", ("Li", "Na", "K", "Rb", "Cs")),
    ("Alkaline Earth Metals", ("Mg", "Ca", "Sr", "Ba")),
    ("Boron Group", ("B", "Al", "Ga", "Tl")),
    ("Carbon Group", ("C", "Si", "Ge", "Sn", "Pb")),
    ("Pnictogens", ("N", "P", "As", "Sb", "Bi")),
    ("Chalcogens", ("O", "S", "Se", "Te")),
    ("Halogens", ("F", "Cl", "Br", "I")),
    (
        "Transition Metals",
        (
            "Ti",
            "V",
            "Cr",
            "Mn",
            "Fe",
            "Co",
            "Ni",
            "Cu",
            "Zn",
            "Mo",
            "Ru",
            "Rh",
            "Pd",
            "Ag",
            "Cd",
            "W",
            "Re",
            "Os",
            "Ir",
            "Pt",
            "Au",
            "Hg",
        ),
    ),
    ("Lanthanides", ("Sm", "Eu", "Gd", "Lu")),
)

# Default left-panel buttons (subset of ELEMENT_FAMILY_GROUPS).
TOOLBAR_ELEMENT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hydrogen Isotopes", ("H", "D", "T")),
    ("Alkali Metals", ("Li", "Na", "K", "Cs")),
    ("Alkaline Earth Metals", ("Mg", "Ca")),
    ("Boron Group", ("B", "Al")),
    ("Carbon Group", ("C", "Si")),
    ("Pnictogens", ("N", "P")),
    ("Chalcogens", ("O", "S", "Se")),
    ("Halogens", ("F", "Cl", "Br", "I")),
    ("Transition Metals", ("Fe", "Ni", "Pd", "Pt", "Cu", "Zn")),
)

TOOLBAR_ELEMENT_SYMBOLS: tuple[str, ...] = tuple(
    el for _title, els in TOOLBAR_ELEMENT_GROUPS for el in els
)

# Short element rail on the sketcher. Everything else from the saved set is under More.
SKETCH_RAIL_ELEMENTS: tuple[str, ...] = (
    "C",
    "N",
    "O",
    "S",
    "F",
    "Cl",
    "Br",
    "I",
    "P",
    "H",
)

# Pixel → model distance scale for 2D stereo perception (bond dirs + coordinates).
SKETCH_COORD_SCALE = 40.0

# Canonical median bond length (px) for hand-drawn bonds, ring templates, RDKit import, and ACS line weights.
SKETCH_MEDIAN_BOND_PX = 60
# Half-width (Å-like units in draw space) at the wide end of wedge / hash triangles.
WEDGE_TRI_HALF_WIDTH = 8.0

# Single-ring sketch templates: (n_atoms, elements clockwise, bond_orders clockwise)
SKETCH_RING_TEMPLATES: dict[str, tuple[int, list[str], list[int]]] = {
    "Benzene": (6, ["C"] * 6, [2 if i % 2 == 0 else 1 for i in range(6)]),
    "Cyclopropane": (3, ["C"] * 3, [1, 1, 1]),
    "Cyclobutane": (4, ["C"] * 4, [1, 1, 1, 1]),
    "Cyclopentyl": (5, ["C"] * 5, [1, 1, 1, 1, 1]),
    "Cyclohexyl": (6, ["C"] * 6, [1, 1, 1, 1, 1, 1]),
    "Cycloheptane": (7, ["C"] * 7, [1] * 7),
    "Cyclooctane": (8, ["C"] * 8, [1] * 8),
    "Cyclononane": (9, ["C"] * 9, [1] * 9),
    "Cyclodecane": (10, ["C"] * 10, [1] * 10),
    "Cycloundecane": (11, ["C"] * 11, [1] * 11),
    "Cyclododecane": (12, ["C"] * 12, [1] * 12),
    "Pyridine": (6, ["N"] + ["C"] * 5, [2 if i % 2 == 0 else 1 for i in range(6)]),
    "Pyrimidine": (
        6,
        ["N", "C", "N", "C", "C", "C"],
        [2 if i % 2 == 0 else 1 for i in range(6)],
    ),
    "Pyrazine": (6, ["N", "C", "N", "C", "C", "C"], [2, 1, 2, 1, 2, 1]),
    "Pyridazine": (6, ["N", "N", "C", "C", "C", "C"], [1, 2, 1, 2, 1, 2]),
    "Triazine": (6, ["N", "C", "N", "C", "N", "C"], [2, 1, 2, 1, 2, 1]),
    "Pyrrole": (5, ["N"] + ["C"] * 4, [1, 2, 1, 2, 1]),
    "Imidazole": (5, ["N", "C", "N", "C", "C"], [1, 2, 1, 2, 1]),
    "Pyrazole": (5, ["N", "N", "C", "C", "C"], [1, 2, 1, 2, 1]),
    "Triazole_124": (5, ["N", "N", "C", "N", "C"], [1, 2, 1, 2, 1]),
    "Triazole_123": (5, ["N", "N", "N", "C", "C"], [1, 2, 1, 2, 1]),
    "Piperidine": (6, ["N", "C", "C", "C", "C", "C"], [1, 1, 1, 1, 1, 1]),
    "Piperazine": (6, ["N", "C", "C", "N", "C", "C"], [1, 1, 1, 1, 1, 1]),
    "Morpholine": (6, ["N", "C", "C", "O", "C", "C"], [1, 1, 1, 1, 1, 1]),
    "Furan": (5, ["O"] + ["C"] * 4, [1, 2, 1, 2, 1]),
    "Oxazole": (5, ["N", "C", "O", "C", "C"], [1, 2, 1, 2, 1]),
    "Isoxazole": (5, ["N", "O", "C", "C", "C"], [1, 2, 1, 2, 1]),
    "THF": (5, ["O", "C", "C", "C", "C"], [1, 1, 1, 1, 1]),
    "Oxetane": (4, ["O", "C", "C", "C"], [1, 1, 1, 1]),
    "Dioxane": (6, ["O", "C", "C", "O", "C", "C"], [1, 1, 1, 1, 1, 1]),
    "Dioxolane": (5, ["O", "C", "O", "C", "C"], [1, 1, 1, 1, 1]),
    "Oxadiazole": (5, ["O", "N", "C", "N", "C"], [1, 2, 1, 2, 1]),
    "Thiophene": (5, ["S"] + ["C"] * 4, [1, 2, 1, 2, 1]),
    "Thiazole": (5, ["N", "C", "S", "C", "C"], [1, 2, 1, 2, 1]),
    "Isothiazole": (5, ["S", "N", "C", "C", "C"], [1, 2, 1, 2, 1]),
    "Thietane": (4, ["S", "C", "C", "C"], [1, 1, 1, 1]),
    "Thiane": (6, ["S", "C", "C", "C", "C", "C"], [1, 1, 1, 1, 1, 1]),
    "Thiadiazole": (5, ["S", "N", "C", "N", "C"], [1, 2, 1, 2, 1]),
}
