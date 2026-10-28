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

"""Bulk delete snapshot helpers (no full main window)."""

from __future__ import annotations

from types import SimpleNamespace

from molmanager.ui.compound_table_model import CompoundTableModel
from molmanager.ui.main_window.table_undo_commands import collect_delete_row_snapshots


def test_collect_delete_row_snapshots_light(qapp):  # noqa: ARG001
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    model = CompoundTableModel(headers)
    for oid, smi, mw in ((1, "C", "16"), (2, "CC", "30"), (3, "CCC", "44")):
        model.append_row(oid, {"SMILES": smi, "MW": mw})
    app = SimpleNamespace(
        headers=headers,
        _table_model=model,
        mols={},
    )
    snaps = collect_delete_row_snapshots(app, frozenset({1, 3}))
    assert len(snaps) == 2
    assert {s.oid for s in snaps} == {1, 3}
    assert all(s.light for s in snaps)
    assert snaps[0].cells["SMILES"] == "C"
    assert snaps[1].cells["MW"] == "44"
    assert snaps[0].mol_copy is None
    assert snaps[0].structure_png is None

    chunk = collect_delete_row_snapshots(app, frozenset({1, 3}), start=1, end=3)
    assert [s.oid for s in chunk] == [3]
    assert chunk[0].orig_row == 2
    assert chunk[0].light
    assert chunk[0].cells["SMILES"] == "CCC"
