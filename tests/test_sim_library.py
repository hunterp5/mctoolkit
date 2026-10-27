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

"""Library cost and replicate summaries."""

from molmanager.sim.library import (
    library_cost_message,
    library_needs_confirmation,
    production_length_ps,
    summarize_replicates,
)
from molmanager.sim.presets import explicit_npt, gb_relax


def test_explicit_preset_production_is_long_enough_to_confirm():
    picoseconds = production_length_ps(explicit_npt())
    assert picoseconds > 10_000
    assert library_needs_confirmation(2, 2, picoseconds)
    assert "2 ligands × 2 replicates" in library_cost_message(2, 2, picoseconds)


def test_short_gb_screen_does_not_require_confirmation():
    assert production_length_ps(gb_relax()) < 1000
    assert library_needs_confirmation(1, 1, 100.0) is False


def test_replicate_summary_mean_and_status():
    rows = [
        {"oid": 1, "label": "a", "status": "ok", "value": 1.0},
        {"oid": 1, "label": "a", "status": "ok", "value": 3.0},
        {"oid": 2, "label": "b", "status": "cancelled", "value": None},
    ]
    summary = {row["oid"]: row for row in summarize_replicates(rows)}
    assert summary[1]["mean"] == 2.0
    assert summary[1]["text"].startswith("2")
    assert summary[2]["status"] == "cancelled"
