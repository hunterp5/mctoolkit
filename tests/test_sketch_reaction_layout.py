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

"""Reaction layout sits beside the sketch widget, not inside the RDKit mixin."""

from __future__ import annotations

from molmanager.ui.sketcher.sketch_reaction_layout import (
    prepared_reaction_mols,
    reaction_centers,
    reaction_from_pattern,
)


def test_products_sit_to_the_right_of_reactants() -> None:
    reaction = reaction_from_pattern("CC.O>>CCO")
    assert reaction is not None
    reactants = prepared_reaction_mols(reaction.GetReactants())
    products = prepared_reaction_mols(reaction.GetProducts())
    placed = reaction_centers(reactants, products)
    assert placed is not None
    left, right, (tail, head) = placed
    assert left and right
    assert max(point.x() for point in left) < min(point.x() for point in right)
    assert tail.x() < head.x()


def test_text_without_a_product_is_not_a_reaction() -> None:
    assert reaction_from_pattern("CCO") is None
    assert reaction_centers([], []) is None
