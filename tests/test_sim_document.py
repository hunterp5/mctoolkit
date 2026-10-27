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

"""Simulation document JSON and the shipped presets."""

from molmanager.sim.document import document_from_json, document_to_json, validate_document
from molmanager.sim.presets import PRESETS, blank, explicit_npt, gb_relax


def test_presets_roundtrip_and_validate():
    for factory in (gb_relax, explicit_npt, blank):
        document = factory()
        again = document_from_json(document_to_json(document))
        assert again.content_hash() == document.content_hash()
        assert validate_document(again) == []
        assert [stage.id for stage in again.stages] == [stage.id for stage in document.stages]


def test_explicit_preset_is_the_heat_then_production_schedule():
    document = explicit_npt()
    assert document.system.solvent == "tip3p"
    assert [stage.name for stage in document.stages] == [
        "Minimize",
        "Heat",
        "Equilibrate NVT",
        "Equilibrate NPT",
        "Production",
    ]
    heat = document.stages[1]
    assert heat.temperature_k == 0.0
    assert heat.temperature_end_k == 300.0
    assert document.stages[-1].length_unit == "ns"


def test_preset_registry_matches_the_factories():
    assert set(PRESETS) == {"gb_relax", "explicit_npt", "blank"}


def test_gaff_dodecahedron_is_rejected():
    document = explicit_npt()
    document.system.box_shape = "dodecahedron"
    issues = validate_document(document)
    assert any("dodecahedron" in issue for issue in issues)
