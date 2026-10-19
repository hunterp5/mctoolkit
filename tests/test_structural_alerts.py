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

"""Structural alert catalogs, column values, and the descriptor tab."""

from __future__ import annotations

from unittest.mock import patch

from rdkit import Chem

from molmanager.chem.structural_alerts import (
    alert_internal_key,
    available_alert_catalogs,
    build_alert_catalog,
    clear_thread_catalog_cache,
)
from molmanager.ui.dialogs.properties import PropertyDialog
from molmanager.workers.chemistry_descriptors import (
    _calc_descriptor_row_values,
    _mp_calc_descriptor_batch,
)


def _mol(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def _alert_row(mol, catalogs: tuple[str, ...]) -> dict[str, str]:
    headers: list[str] = []
    keys: list[str] = []
    labels = {spec.key: spec.label for spec in available_alert_catalogs()}
    for key in catalogs:
        label = labels[key]
        headers.extend([f"{label} count", f"{label} alerts"])
        keys.extend([alert_internal_key(key, "count"), alert_internal_key(key, "names")])
    _idx, row = _calc_descriptor_row_values(
        1,
        mol,
        headers,
        tuple(keys),
        {},
        pka_states=None,
        pka_cache_used=False,
    )
    return row


def test_core_catalogs_are_on_the_descriptor_tab() -> None:
    keys = [spec.key for spec in available_alert_catalogs()]
    assert keys[:4] == ["PAINS", "BRENK", "NIH", "ZINC"]


def test_alerts_tab_starts_unchecked_and_expands_columns(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=2)
    labels = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert labels[labels.index("Drug-likeness") + 1] == "Structural Alerts"
    assert dlg.get_selected() == ([], [])
    dlg._alert_checks["PAINS"].setChecked(True)
    dlg.cbs["Mol Weight"][0].setChecked(True)
    disp, fns = dlg.get_selected()
    assert disp == ["Mol Weight", "PAINS count", "PAINS alerts"]
    assert fns == ["MolWt", "ALERT:PAINS:count", "ALERT:PAINS:names"]
    dlg.close()


def test_ethanol_matches_nothing() -> None:
    row = _alert_row(_mol("CCO"), ("PAINS", "BRENK", "NIH", "ZINC"))
    assert row["PAINS count"] == "0"
    assert row["PAINS alerts"] == ""
    assert row["Brenk count"] == "0"
    assert row["Brenk alerts"] == ""
    assert row["NIH count"] == "0"
    assert row["ZINC count"] == "0"


def test_quinone_hits_pains_and_brenk() -> None:
    row = _alert_row(_mol("O=C1C=CC(=O)C=C1"), ("PAINS", "BRENK"))
    assert row["PAINS count"] == "1"
    assert "quinone_A" in row["PAINS alerts"]
    assert row["Brenk count"] == "1"
    assert row["Brenk alerts"] == "chinone_1"


def test_aniline_hits_brenk_only() -> None:
    row = _alert_row(_mol("Nc1ccccc1"), ("PAINS", "BRENK"))
    assert row["PAINS count"] == "0"
    assert row["PAINS alerts"] == ""
    assert row["Brenk alerts"] == "aniline"


def test_invalid_structure_is_na() -> None:
    _idx, row = _calc_descriptor_row_values(
        1,
        None,
        ["PAINS count", "PAINS alerts"],
        (alert_internal_key("PAINS", "count"), alert_internal_key("PAINS", "names")),
        {},
        pka_states=None,
        pka_cache_used=False,
    )
    assert row == {"PAINS count": "N/A", "PAINS alerts": "N/A"}


def test_catalog_is_built_once_per_thread() -> None:
    clear_thread_catalog_cache()
    mol = _mol("CCO")
    with patch(
        "molmanager.chem.structural_alerts.build_alert_catalog",
        wraps=build_alert_catalog,
    ) as spy:
        row = _alert_row(mol, ("PAINS",))
        again = _alert_row(mol, ("PAINS",))
        assert row["PAINS count"] == again["PAINS count"] == "0"
        assert spy.call_count == 1


def test_process_batch_entry_point_writes_alert_columns() -> None:
    mol = _mol("O=C1C=CC(=O)C=C1")
    rows = _mp_calc_descriptor_batch(
        (
            [(7, mol.ToBinary(), None, b"")],
            ("PAINS count", "PAINS alerts"),
            (alert_internal_key("PAINS", "count"), alert_internal_key("PAINS", "names")),
            False,
        )
    )
    assert rows[0][0] == 7
    assert rows[0][1]["PAINS count"] == "1"
    assert "quinone_A" in rows[0][1]["PAINS alerts"]
