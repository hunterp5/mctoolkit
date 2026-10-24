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

"""Shared table-rows vs SMILES input panel."""

from __future__ import annotations

from pathlib import Path

from molmanager.ui.dialogs.structure_input import (
    STRUCTURE_INPUT_MODE_LABELS,
    StructureInputPanel,
)


def test_structure_input_panel_mode_keys(qapp) -> None:  # noqa: ARG001
    panel = StructureInputPanel(selected_row_count=0)
    keys = [panel.mode_combo.itemData(i) for i in range(panel.mode_combo.count())]
    assert keys == [k for k, _ in STRUCTURE_INPUT_MODE_LABELS]
    assert panel.mode() == "table"
    assert not panel._table_cfg.isHidden()
    assert panel._smiles_cfg.isHidden()
    panel.mode_combo.setCurrentIndex(keys.index("smiles"))
    assert panel.mode() == "smiles"
    assert not panel._smiles_cfg.isHidden()
    assert panel._table_cfg.isHidden()


def test_predict_dialogs_use_shared_structure_input() -> None:
    root = Path(__file__).resolve().parents[1] / "molmanager" / "ui" / "dialogs"
    for name in ("pka.py", "protomer.py", "biotransformer.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "from .structure_input import attach_structure_input" in text
        assert "currentIndex() == 1" not in text
        assert "from rdkit import Chem" not in text
