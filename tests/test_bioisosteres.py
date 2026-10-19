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

"""Bioisostere dictionary: every SMIRKS parses and its example product is real."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.bioisosteres import (
    BIOISOSTERES,
    CATEGORY_LABELS,
    apply_bioisostere,
    apply_bioisosteres,
    bioisosteres_in,
    get_bioisostere,
    site_count,
)


def test_dictionary_keys_and_categories_are_unique() -> None:
    keys = [row.key for row in BIOISOSTERES]
    assert len(keys) == len(set(keys))
    assert keys == sorted(keys, key=keys.index)
    categories = {row.category for row in BIOISOSTERES}
    assert categories == set(CATEGORY_LABELS)
    assert sum(len(bioisosteres_in(category)) for category in CATEGORY_LABELS) == len(BIOISOSTERES)


def test_every_transform_makes_its_example_product() -> None:
    for row in BIOISOSTERES:
        products = apply_bioisostere(row.example_in, row)
        assert row.example_out in products, (row.key, products)
        assert row.example_in not in products or row.example_out != row.example_in


def test_each_smirks_is_one_reactant_to_one_product() -> None:
    for row in BIOISOSTERES:
        assert ">>" in row.smirks
        assert row.smirks.count(">>") == 1
        assert site_count(row.example_in, row.key) >= 1


def test_guards_skip_the_wrong_functional_group() -> None:
    assert apply_bioisostere("CC(=O)OC", "acid_to_tetrazole") == ()
    assert apply_bioisostere("O=C1CCC(=O)N1", "amide_to_ester") == ()
    assert apply_bioisostere("COc1ccccc1", "c_methyl_to_fluoromethyl") == ()
    assert apply_bioisostere("c1ccc2[nH]ccc2c1", "pyrrole_to_furan") == ()
    assert apply_bioisostere("c1ccc2ncccc2c1", "pyridine_to_piperidine") == ()


def test_symmetric_sites_collapse_to_one_product() -> None:
    assert apply_bioisostere("c1ccccc1", "aryl_h_to_f") == ("Fc1ccccc1",)
    assert apply_bioisostere("c1ccccc1", "aryl_ch_to_n") == ("c1ccncc1",)
    assert site_count("c1ccccc1", "aryl_h_to_f") == 6


def test_cubane_product_is_the_cage() -> None:
    product = Chem.MolFromSmiles(get_bioisostere("para_phenyl_to_cubane").example_out)
    assert product is not None
    four_rings = [ring for ring in product.GetRingInfo().AtomRings() if len(ring) == 4]
    assert len(four_rings) >= 5


def test_two_transforms_keep_their_own_keys() -> None:
    pairs = apply_bioisosteres("CC(=O)O", ("acid_to_tetrazole", "acid_to_hydroxamic"))
    assert ("acid_to_tetrazole", "Cc1nn[nH]n1") in pairs
    assert ("acid_to_hydroxamic", "CC(=O)NO") in pairs


def test_unknown_key_raises() -> None:
    try:
        get_bioisostere("not_a_transform")
    except KeyError:
        return
    raise AssertionError("expected KeyError")
