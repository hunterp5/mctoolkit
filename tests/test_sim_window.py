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

"""Simulation workspace window."""

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.sim.document import validate_document
from molmanager.ui.simulation.window import SimulationWindow


def test_window_edits_a_dynamics_stage(qapp):  # noqa: ARG001
    window = SimulationWindow(None)
    assert window._stages.count() == 5
    window._stages.setCurrentRow(1)
    window._temperature.setValue(50)
    window._use_temperature_ramp.setChecked(True)
    window._temperature_end.setValue(300)
    window._read_stage()
    heat = window.document.stages[1]
    assert heat.temperature_k == 50
    assert heat.temperature_end_k == 300
    window._read_all()
    assert validate_document(window.document) == []
    window.close()
