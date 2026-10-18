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

"""Free-Wilson fit, missing-analog enumeration, and refusal limits."""

from __future__ import annotations

from rdkit import Chem

from molmanager.analysis.free_wilson import (
    REPORT_FREE_WILSON,
    REPORT_FUJITA_BAN,
    SKIP_NO_MATCH,
    SKIP_RARE,
    FreeWilsonSettings,
    run_free_wilson,
)

_CORE = "Cc1cc([*:1])ccc1[*:2]"
_HH = "Cc1ccccc1"
_ME_H = "Cc1cc(C)ccc1"
_CL_H = "Cc1cc(Cl)ccc1"
_H_F = "Cc1ccccc1F"
_ME_F = "Cc1cc(C)ccc1F"
_CL_F = "Cc1cc(Cl)ccc1F"
_BR_H = "Cc1cc(Br)ccc1"


def _records(*pairs: tuple[str, float]) -> list[tuple[int, Chem.Mol, float]]:
    rows: list[tuple[int, Chem.Mol, float]] = []
    for index, (smiles, activity) in enumerate(pairs, start=1):
        mol = Chem.MolFromSmiles(smiles)
        assert mol is not None
        rows.append((index, mol, activity))
    return rows


def _settings(**kwargs: object) -> FreeWilsonSettings:
    payload: dict[str, object] = {"core_query": _CORE, "min_count": 1, "max_new_structures": 20}
    payload.update(kwargs)
    return FreeWilsonSettings(**payload)  # type: ignore[arg-type]


def _canonical(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return Chem.MolToSmiles(mol, canonical=True)


def test_dialog_defaults_to_fujita_ban(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.free_wilson import FreeWilsonDialog

    dialog = FreeWilsonDialog(
        structure_sources=["Structure"],
        activity_columns=["pIC50"],
        selected_row_count=0,
    )
    dialog.core_edit.setText(_CORE)
    params = dialog.params()
    assert params.structure_source == "Structure"
    assert params.settings.activity_column == "pIC50"
    assert params.settings.report == REPORT_FUJITA_BAN
    assert params.settings.min_count == 2
    assert params.settings.prefer_higher is True
    assert params.settings.only_match_at_r_groups is True
    assert params.settings.core_query == _CORE
    dialog.deleteLater()


def test_fujita_ban_recovers_hydrogen_reference_and_missing_analog() -> None:
    result = run_free_wilson(
        _records(
            (_HH, 1.0),
            (_ME_H, 1.5),
            (_CL_H, 3.0),
            (_H_F, 4.0),
            (_ME_F, 4.5),
            ("CCO", 9.0),
        ),
        _settings(report=REPORT_FUJITA_BAN),
    )
    assert result.ok
    assert result.report == REPORT_FUJITA_BAN
    assert result.n == 5
    assert abs(result.intercept - 1.0) < 1e-6
    assert result.r_squared is not None and abs(result.r_squared - 1.0) < 1e-6
    by_key = {(coef.position, coef.key): coef for coef in result.coefficients}
    assert by_key[("R1", "H")].is_reference
    assert abs(by_key[("R1", "H")].coefficient - 0.0) < 1e-8
    assert abs(by_key[("R1", "*C")].coefficient - 0.5) < 1e-6
    assert abs(by_key[("R1", "*Cl")].coefficient - 2.0) < 1e-6
    assert abs(by_key[("R2", "*F")].coefficient - 3.0) < 1e-6
    assert any(row.oid == 6 and row.reason == SKIP_NO_MATCH for row in result.skipped)
    assert len(result.missing) == 1
    missing = result.missing[0]
    assert missing.smiles == _canonical(_CL_F)
    assert abs(missing.predicted - 6.0) < 1e-6
    observed = {_canonical(smiles) for smiles in (_HH, _ME_H, _CL_H, _H_F, _ME_F)}
    assert missing.smiles not in observed
    assert all(item.smiles not in observed for item in result.missing)


def test_free_wilson_coefficients_sum_to_zero_and_match_predictions() -> None:
    records = _records(
        (_HH, 1.0),
        (_ME_H, 1.5),
        (_CL_H, 3.0),
        (_H_F, 4.0),
        (_ME_F, 4.5),
    )
    fujita = run_free_wilson(records, _settings(report=REPORT_FUJITA_BAN))
    classic = run_free_wilson(records, _settings(report=REPORT_FREE_WILSON))
    assert classic.ok and classic.report == REPORT_FREE_WILSON
    totals: dict[str, float] = {}
    for coef in classic.coefficients:
        assert coef.identifiable and coef.coefficient is not None
        totals[coef.position] = totals.get(coef.position, 0.0) + coef.count * coef.coefficient
    assert totals
    assert all(abs(total) < 1e-6 for total in totals.values())
    assert [round(row.predicted, 6) for row in fujita.observed] == [
        round(row.predicted, 6) for row in classic.observed
    ]


def test_rare_substituents_and_unmatched_cores_are_excluded() -> None:
    result = run_free_wilson(
        _records(
            (_HH, 1.0),
            (_ME_H, 1.5),
            (_CL_H, 3.0),
            (_H_F, 4.0),
            (_ME_F, 4.5),
            (_BR_H, 8.0),
            ("CCO", 9.0),
        ),
        _settings(min_count=2),
    )
    assert result.ok
    assert result.n == 4
    reasons = {row.oid: row.reason for row in result.skipped}
    assert reasons[3] == SKIP_RARE
    assert reasons[6] == SKIP_RARE
    assert reasons[7] == SKIP_NO_MATCH
    fitted_keys = {coef.key for coef in result.coefficients}
    assert "*Cl" not in fitted_keys
    assert "*Br" not in fitted_keys


def test_enumeration_keeps_the_requested_extreme() -> None:
    records = _records(
        (_HH, 1.0),
        (_ME_H, 1.5),
        (_CL_H, 3.0),
        (_H_F, 4.0),
    )
    highest = run_free_wilson(
        records,
        _settings(max_new_structures=1, prefer_higher=True),
    )
    lowest = run_free_wilson(
        records,
        _settings(max_new_structures=1, prefer_higher=False),
    )
    assert highest.enumeration_truncated and highest.n_missing == 2
    assert lowest.enumeration_truncated
    assert len(highest.missing) == 1
    assert len(lowest.missing) == 1
    assert highest.missing[0].smiles == _canonical(_CL_F)
    assert lowest.missing[0].smiles == _canonical(_ME_F)
    assert highest.missing[0].predicted > lowest.missing[0].predicted


def test_product_over_the_limit_refuses_instead_of_sampling() -> None:
    result = run_free_wilson(
        _records((_HH, 1.0), (_ME_H, 1.5), (_H_F, 4.0)),
        _settings(max_new_structures=10),
        enumeration_product_limit=3,
    )
    assert result.ok
    assert result.enumeration_refused
    assert result.missing == ()
    assert result.n_combinations == 4
    assert result.position_counts == (("R1", 2), ("R2", 2))
    assert "exceeds" in result.enumeration_message
    assert "No partial" in result.enumeration_message
    assert result.n == 3
    assert result.saturated


def test_aliased_substituent_is_not_identifiable() -> None:
    result = run_free_wilson(
        _records(
            (_HH, 1.0),
            (_ME_F, 4.0),
            (_ME_F, 4.2),
            (_CL_H, 3.0),
        ),
        _settings(),
    )
    assert result.ok
    hidden = [coef for coef in result.coefficients if not coef.identifiable]
    assert hidden
    assert all(coef.coefficient is None for coef in hidden)
