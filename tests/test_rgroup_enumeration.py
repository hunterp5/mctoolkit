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

"""R-group enumeration: numbered cores, building-block lists, and product rows."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.rgroup_enumeration import (
    CORE_ID_HEADER,
    RGroupEnumerationRequest,
    RGroupPool,
    RGroupPoolInput,
    BuildingBlock,
    building_blocks_from_text,
    enumerate_rgroups,
    prepare_core,
    write_rgroup_products_to_sdf,
)
from molmanager.workers.rgroup_enumeration import RGroupEnumerationWorker
from molmanager.workers.signals import WorkerSignals


def _pool(label: int, text: str) -> RGroupPool:
    return RGroupPool(label, building_blocks_from_text(label, text))


def test_aniline_attaches_through_the_starred_nitrogen():
    products, skipped, cancelled = enumerate_rgroups(
        "c1ccccc1[*:1]",
        [_pool(1, "CCN* ethylamine")],
        core_id="phenyl",
    )
    assert not cancelled
    assert skipped == 0
    assert len(products) == 1
    assert products[0].smiles == "CCNc1ccccc1"
    assert products[0].core_id == "phenyl"
    assert products[0].reagent_ids == ((1, "ethylamine"),)
    assert products[0].field_map()[CORE_ID_HEADER] == "phenyl"
    assert products[0].field_map()["R1"] == "ethylamine"


def test_two_points_are_the_cartesian_product_and_a_cap_is_toluene():
    products, _skipped, cancelled = enumerate_rgroups(
        "[*:1]c1ccc([*:2])cc1",
        [_pool(1, "C* methyl\nCC* ethyl"), _pool(2, "N*\nO*")],
    )
    assert not cancelled
    pairs = {(dict(product.reagent_ids)[1], dict(product.reagent_ids)[2]) for product in products}
    assert pairs == {("methyl", "R2-1"), ("methyl", "R2-2"), ("ethyl", "R2-1"), ("ethyl", "R2-2")}
    assert all(Chem.MolFromSmiles(product.smiles).GetNumAtoms() > 0 for product in products)
    assert all("*" not in product.smiles for product in products)

    capped, _skipped, _cancelled = enumerate_rgroups(
        "[*:1]c1ccccc1",
        [_pool(1, "*")],
    )
    assert [product.smiles for product in capped] == ["c1ccccc1"]

    toluene, _skipped, _cancelled = enumerate_rgroups(
        "[*:1]c1ccc([*:2])cc1",
        [_pool(1, "C*"), _pool(2, "[H]")],
    )
    assert [product.smiles for product in toluene] == ["Cc1ccccc1"]


def test_property_filter_drops_the_heavy_product():
    products, skipped, _cancelled = enumerate_rgroups(
        "c1ccccc1[*:1]",
        [_pool(1, "C*\nCCCCCCCCCCCC*")],
        max_products=10,
        output_filters="MW <= 120",
    )
    assert [product.smiles for product in products] == ["Cc1ccccc1"]
    assert skipped == 1


def test_core_labels_accept_isotope_and_unnumbered_stars():
    _mol, isotope = prepare_core("[1*]c1ccc([2*])cc1")
    assert isotope == (1, 2)
    _mol, ordered = prepare_core("*c1ccc(*)cc1")
    assert ordered == (1, 2)
    products, _skipped, _cancelled = enumerate_rgroups(
        "*c1ccc(*)cc1", [_pool(1, "C*"), _pool(2, "N*")]
    )
    assert len(products) == 1
    mol = Chem.MolFromSmiles(products[0].smiles)
    assert mol is not None
    assert mol.HasSubstructMatch(Chem.MolFromSmiles("Cc1ccccc1"))
    assert mol.HasSubstructMatch(Chem.MolFromSmiles("Nc1ccccc1"))


def test_missing_attachment_and_a_block_without_a_star_are_errors():
    try:
        prepare_core("c1ccccc1")
    except ValueError as exc:
        assert "attachment point" in str(exc)
    else:
        raise AssertionError("a core without * should fail")
    try:
        building_blocks_from_text(1, "CC")
    except ValueError as exc:
        assert "R1" in str(exc)
    else:
        raise AssertionError("a block without * should fail")


def test_sdf_keeps_core_and_reagent_ids(tmp_path):
    products, _skipped, _cancelled = enumerate_rgroups(
        "c1ccccc1[*:1]",
        [_pool(1, "C* methyl")],
        core_id="phenyl",
    )
    path = tmp_path / "products.sdf"
    assert write_rgroup_products_to_sdf(path, products) == 1
    supplier = Chem.SDMolSupplier(str(path), removeHs=True)
    mol = next(iter(supplier))
    assert mol is not None
    assert mol.GetProp("Core_ID") == "phenyl"
    assert mol.GetProp("R1") == "methyl"


def test_worker_emits_one_product(qapp):
    del qapp
    request = RGroupEnumerationRequest(
        core_smiles="c1ccccc1[*:1]",
        core_id="phenyl",
        pools=(RGroupPoolInput(1, "smiles", "", "C* methyl"),),
        max_products=10,
        output_filters="",
        add_to_table=True,
        save_to_file=False,
        save_path=None,
    )
    signals = WorkerSignals()
    out: dict[str, object] = {}
    signals.rgroup_enum_finished.connect(lambda result: out.update({"result": result}))
    signals.rgroup_enum_failed.connect(lambda message, _title: out.update({"failed": message}))
    RGroupEnumerationWorker(request, "R-Group Enumeration", signals).run()
    assert "failed" not in out
    result = out["result"]
    assert result.products[0].smiles == "Cc1ccccc1"
    assert result.products[0].reagent_ids == ((1, "methyl"),)
    assert result.add_to_table is True


def test_dialog_builds_a_list_per_attachment_point(qapp):
    del qapp
    from molmanager.ui.dialogs.rgroup_enumeration import RGroupEnumerationDialog

    dialog = RGroupEnumerationDialog()
    try:
        dialog.show()
        dialog.core_edit.setText("[*:1]c1ccc([*:2])cc1")
        assert dialog.sync_attachment_points() is None
        assert [panel.core_label for panel in dialog._panels] == [1, 2]
        assert dialog._panels[0].point_edit.text() == "R1"
        assert not hasattr(dialog, "hint")
        dialog._panels[0].file_edit.setText("amines.smi")
        dialog._panels[1].point_edit.setText("2")
        dialog._panels[1].file_edit.setText("acids.sdf")
        dialog.core_id_edit.setText("para")
        request = dialog.request()
        assert request.core_id == "para"
        assert [pool.label for pool in request.pools] == [1, 2]
        assert request.pools[0].mode == "file"
        assert request.pools[0].file_path == "amines.smi"
        assert request.pools[1].file_path == "acids.sdf"
        assert request.add_to_table is True
    finally:
        dialog.close()


def test_building_block_type_is_used():
    """Keep the dataclass import honest for a hand-built pool."""
    core, labels = prepare_core("c1ccccc1[*:1]")
    assert labels == (1,)
    mol = Chem.MolFromSmiles("C*")
    assert mol is not None
    products, _skipped, _cancelled = enumerate_rgroups(
        "c1ccccc1[*:1]",
        [RGroupPool(1, (BuildingBlock("methyl", mol),))],
        core_id="phenyl",
    )
    assert products[0].smiles == "Cc1ccccc1"
    assert core.GetNumAtoms() > 1
