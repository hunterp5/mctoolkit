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

"""Hansch fit on a shared core. Constant values here are synthetic."""

from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox, QTextEdit
from rdkit import Chem

from molmanager.analysis.hansch import (
    ELECTRONIC_NONE,
    ELECTRONIC_SIGMA,
    SIGMA_META,
    SIGMA_PARA,
    SKIP_NO_MATCH,
    SKIP_UNMATCHED,
    STERIC_ES,
    STERIC_NONE,
    HanschSettings,
    parse_sigma_assignments,
    run_hansch,
)

_CORE = "Cc1cc([*:1])ccc1[*:2]"
_ONE = "c1ccc([*:1])cc1"
_CONSTANTS = """smiles,pi,sigma_m,sigma_p,f,r,es,mr,upsilon,sigma_star
H,0,0,0,0,0,0,0,0,0
*C,1,0,0,0,0,-1.1,0.5,0.5,0
*Cl,0,0.4,1,0.4,0.2,-0.2,0.6,0.55,0
*CC,2,0,0,0,0,0,1,0.7,0
"""


def _records(*pairs: tuple[str, float]) -> list[tuple[int, Chem.Mol, float]]:
    rows: list[tuple[int, Chem.Mol, float]] = []
    for index, (smiles, activity) in enumerate(pairs, start=1):
        mol = Chem.MolFromSmiles(smiles)
        assert mol is not None
        rows.append((index, mol, activity))
    return rows


def _write_constants(tmp_path) -> str:
    path = tmp_path / "constants.csv"
    path.write_text(_CONSTANTS, encoding="utf-8")
    return str(path)


def _settings(path: str, **kwargs: object) -> HanschSettings:
    payload: dict[str, object] = {
        "core_query": _CORE,
        "constants_path": path,
        "activity_column": "pIC50",
    }
    payload.update(kwargs)
    return HanschSettings(**payload)  # type: ignore[arg-type]


def test_parse_sigma_assignments() -> None:
    assert parse_sigma_assignments("R1=meta, R2=para") == {"R1": SIGMA_META, "R2": SIGMA_PARA}
    assert parse_sigma_assignments("R3 m") == {"R3": SIGMA_META}


def test_two_positions_recover_pi_and_sigma(tmp_path) -> None:
    path = _write_constants(tmp_path)
    result = run_hansch(
        _records(
            ("Cc1ccccc1", 1.0),
            ("Cc1cc(C)ccc1", 3.0),
            ("Cc1ccccc1Cl", 5.0),
            ("Cc1cc(C)ccc1Cl", 7.0),
            ("CCO", 9.0),
            ("Cc1cc(Br)ccc1", 0.0),
        ),
        _settings(path),
    )
    assert result.ok
    assert result.n == 4
    assert abs(result.intercept - 1.0) < 1e-6
    assert result.r_squared is not None and abs(result.r_squared - 1.0) < 1e-6
    assert result.q_squared is not None and abs(result.q_squared - 1.0) < 1e-6
    by_name = {item.name: item for item in result.coefficients}
    assert abs(by_name["R1 π"].coefficient - 2.0) < 1e-6
    assert abs(by_name["R2 σp"].coefficient - 4.0) < 1e-6
    assert by_name["R1 σp"].identifiable is False
    assert by_name["R2 π"].identifiable is False
    assert "pIC50 = 1 + 2*R1 π + 4*R2 σp" == result.equation
    assert any(row.reason == SKIP_NO_MATCH for row in result.skipped)
    assert any(row.reason == SKIP_UNMATCHED for row in result.skipped)
    assert ("R1", "*Br") in result.unmatched or any(
        key.endswith("Br") for _pos, key in result.unmatched
    )


def test_pi_squared_and_stored_es(tmp_path) -> None:
    path = _write_constants(tmp_path)
    squared = run_hansch(
        _records(
            ("c1ccccc1", 0.0),
            ("c1ccccc1C", 1.0),
            ("c1ccccc1CC", 4.0),
        ),
        _settings(
            path,
            core_query=_ONE,
            include_pi=True,
            include_pi_squared=True,
            electronic=ELECTRONIC_NONE,
        ),
    )
    assert squared.ok and squared.saturated
    by_name = {item.name: item for item in squared.coefficients}
    assert abs(by_name["R1 π"].coefficient - 0.0) < 1e-6
    assert abs(by_name["R1 π²"].coefficient - 1.0) < 1e-6
    assert squared.q_squared is None

    steric = run_hansch(
        _records(("c1ccccc1", 0.0), ("c1ccccc1C", -1.1)),
        _settings(
            path,
            core_query=_ONE,
            include_pi=False,
            electronic=ELECTRONIC_NONE,
            steric=STERIC_ES,
        ),
    )
    assert steric.ok
    es = next(item for item in steric.coefficients if item.name == "R1 Es")
    assert es.identifiable
    assert es.coefficient is not None and abs(es.coefficient - 1.0) < 1e-6


def test_dialog_defaults(qapp, tmp_path) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.hansch import HanschDialog

    dialog = HanschDialog(
        structure_sources=["Structure"],
        activity_columns=["pIC50"],
        selected_row_count=0,
    )
    dialog.core_edit.setText(_ONE)
    dialog.constants_edit.setText(str(tmp_path / "constants.csv"))
    dialog.sigma_edit.setText("R2=meta")
    params = dialog.params()
    assert params.structure_source == "Structure"
    assert params.settings.activity_column == "pIC50"
    assert params.settings.include_pi is True
    assert params.settings.include_pi_squared is False
    assert params.settings.electronic == ELECTRONIC_SIGMA
    assert params.settings.sigma_default == SIGMA_PARA
    assert params.settings.sigma_positions == (("R2", SIGMA_META),)
    assert params.settings.steric == STERIC_NONE
    assert params.settings.only_match_at_r_groups is True
    assert [box.title() for box in dialog.findChildren(QGroupBox)] == [
        "Activity",
        "Core",
        "Constants",
        "Terms",
    ]
    dialog.deleteLater()


def test_results_dialog_shows_equation(qapp, tmp_path) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.hansch_results import HanschResultsDialog

    path = _write_constants(tmp_path)
    result = run_hansch(
        _records(
            ("Cc1ccccc1", 1.0),
            ("Cc1cc(C)ccc1", 3.0),
            ("Cc1ccccc1Cl", 5.0),
            ("Cc1cc(C)ccc1Cl", 7.0),
        ),
        _settings(path),
    )
    assert result.ok
    dialog = HanschResultsDialog(result)
    text = dialog.findChild(QTextEdit)
    assert text is not None
    assert result.equation in text.toPlainText()
    dialog.deleteLater()
