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

"""Alchemical star maps, charge refusal, and OpenFE settings."""

import pytest

from molmanager.sim.document import RunSpec
from molmanager.sim.fep import (
    ChargeMismatch,
    apply_openfe_settings,
    describe_fep,
    edges_from_charges,
    lambda_schedule,
    refuse_charge_change,
    star_edges,
)


def test_star_and_equal_charge():
    assert star_edges("ref", ["ref", "a", "b"]) == [("ref", "a"), ("ref", "b")]
    assert refuse_charge_change(0, 0) is None
    message = refuse_charge_change(0, 1)
    assert message is not None
    assert "+0" in message and "+1" in message
    with pytest.raises(ChargeMismatch, match="equal net charge"):
        edges_from_charges("ref", {"ref": 0, "a": 0, "b": 1})
    edges = edges_from_charges("ref", {"ref": 0, "a": 0})
    assert [(edge.reference_id, edge.other_id) for edge in edges] == [("ref", "a")]


def test_lambda_schedule_and_settings_overlay():
    assert lambda_schedule(3, None) == [0.0, 0.5, 1.0]
    assert lambda_schedule(12, [0.0, 1.0]) == [0.0, 1.0]
    spec = RunSpec(lambda_values=[0.0, 0.5, 1.0], fep_replica_exchange=False, fep_repeats=2)

    class _Bag:
        def __init__(self) -> None:
            self.simulation_settings = self
            self.sampler_settings = self
            self.equilibration_length = None
            self.production_length = None
            self.sampler_method = ""
            self.protocol_repeats = 1

    bag = _Bag()
    applied = apply_openfe_settings(bag, spec)
    assert "equilibration_length" in applied
    assert "sampler_method" in applied
    assert bag.sampler_method == "independent"
    assert bag.protocol_repeats == 2
    described = describe_fep(spec)
    assert described["lambdas"] == [0.0, 0.5, 1.0]
    assert described["replica_exchange"] is False
