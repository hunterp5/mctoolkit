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

"""Potency unit conversion, Cheng–Prusoff Ki, and the standardization dialog."""

from __future__ import annotations

import math

from PyQt5.QtWidgets import QLabel

from molmanager.chem.potency import (
    canonical_concentration_unit,
    cheng_prusoff_ki,
    cheng_prusoff_terms,
    output_headers,
    p_activity,
    parse_concentration,
    standardize_activity,
    to_molar,
)


def test_concentration_units_become_molar_and_p_activity():
    assert math.isclose(to_molar(100, "nM"), 1e-7)
    assert math.isclose(to_molar(1, "µM"), 1e-6)
    assert math.isclose(to_molar(1, "uM"), 1e-6)
    assert to_molar(2, "M") == 2
    assert math.isclose(p_activity(1e-7) or 0, 7)
    assert math.isclose(p_activity(1e-6) or 0, 6)


def test_unit_column_text_maps_to_a_concentration_unit():
    assert canonical_concentration_unit("nM") == "nM"
    assert canonical_concentration_unit("uM") == "µM"
    assert canonical_concentration_unit("µM") == "µM"
    assert canonical_concentration_unit("μM") == "µM"
    assert canonical_concentration_unit(" nmol/L ") == "nM"
    assert canonical_concentration_unit("(mM)") == "mM"
    assert canonical_concentration_unit("") is None
    assert canonical_concentration_unit("g/mol") is None
    assert canonical_concentration_unit("mg/mL") == "mg/mL"
    assert canonical_concentration_unit("ug/ml") == "µg/mL"
    assert canonical_concentration_unit("g/L") == "g/L"


def test_standardize_writes_desired_unit_and_p_activity():
    cells = standardize_activity(
        "100",
        unit="nM",
        measure="IC50",
        desired_unit="nM",
        write_p=True,
    )
    assert cells == {"IC50 (nM)": "100", "pIC50": "7.000"}
    converted = standardize_activity(
        "100",
        unit=canonical_concentration_unit("uM"),
        measure="Ki",
        desired_unit="nM",
        write_p=False,
    )
    assert converted == {"Ki (nM)": "100000"}
    assert output_headers("IC50", desired_unit="uM", write_p=True, write_ki=False) == [
        "IC50 (uM)",
        "pIC50",
    ]


def test_mass_concentration_uses_molecular_weight():
    molar = to_molar(1, "mg/mL", molar_mass=250)
    assert math.isclose(molar, 0.004)
    assert math.isclose(to_molar(10, "g/L", molar_mass=100), 0.1)
    assert math.isclose(to_molar(1, "ug.mL-1", molar_mass=500), 2e-6)
    cells = standardize_activity(
        "1",
        unit="mg/mL",
        measure="IC50",
        desired_unit="nM",
        write_p=False,
        molar_mass=250,
    )
    assert cells == {"IC50 (nM)": "4e+06"}
    missing = standardize_activity(
        "1",
        unit="g/mL",
        measure="IC50",
        desired_unit="uM",
        write_p=True,
    )
    assert missing == {"IC50 (uM)": "", "pIC50": ""}
    unchanged = to_molar(100, "nM", molar_mass=250)
    assert math.isclose(unchanged, 1e-7)


def test_censored_and_nonpositive_values_stay_blank():
    for text in ("", "  ", ">10000", "<1", "~5", "n.d.", "0", "-3"):
        cells = standardize_activity(
            text,
            unit="nM",
            measure="Ki",
            desired_unit="nM",
            write_p=True,
        )
        assert cells == {"Ki (nM)": "", "pKi": ""}, text
    unknown = standardize_activity(
        "100",
        unit=canonical_concentration_unit("g/mol"),
        measure="IC50",
        desired_unit="uM",
        write_p=True,
    )
    assert unknown == {"IC50 (uM)": "", "pIC50": ""}


def test_cheng_prusoff_halves_ic50_when_substrate_equals_km():
    ic50 = to_molar(100, "nM")
    km = to_molar(1, "µM")
    ki = cheng_prusoff_ki(ic50, km, km)
    assert ki is not None
    assert abs(ki - ic50 / 2) < 1e-18
    cells = standardize_activity(
        "100",
        unit="nM",
        measure="IC50",
        desired_unit="nM",
        write_p=True,
        write_ki=True,
        assay_terms=((km, km),),
    )
    assert cells["IC50 (nM)"] == "100"
    assert cells["pIC50"] == "7.000"
    assert cells["Ki (nM)"] == "50"
    assert cells["pKi"] == "7.301"
    assert output_headers("IC50", desired_unit="nM", write_p=True, write_ki=True) == [
        "IC50 (nM)",
        "pIC50",
        "Ki (nM)",
        "pKi",
    ]


def test_cheng_prusoff_adds_each_assay_concentration():
    ic50 = to_molar(100, "nM")
    km = to_molar(1, "µM")
    ki = cheng_prusoff_terms(ic50, ((km, km), (km, km)))
    assert ki is not None
    assert abs(ki - ic50 / 3) < 1e-18
    assert cheng_prusoff_terms(ic50, ()) is None


def test_cheng_prusoff_controls_follow_the_ic50_measure(qapp) -> None:
    from molmanager.ui.dialogs.potency import PotencyStandardizationDialog

    dlg = PotencyStandardizationDialog(["IC50", "Km"], 0, unit_columns=["Unit", "IC50"])
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.measure_combo.currentData() == "IC50"
        assert dlg.column_combo.currentText() == "IC50"
        assert dlg.unit_column_combo.currentText() == "Unit"
        assert [dlg.desired_unit.itemText(i) for i in range(dlg.desired_unit.count())] == [
            "nM",
            "uM",
        ]
        assert dlg.chk_p.isChecked()
        assert dlg.mw_combo.currentData() == ""
        mw_dlg = PotencyStandardizationDialog(["IC50", "MolWt"], 0, unit_columns=["Unit"])
        assert mw_dlg.mw_combo.currentData() == "MolWt"
        mw_dlg.close()
        assert not hasattr(dlg, "chk_molar")
        assert all("left blank" not in label.text() for label in dlg.findChildren(QLabel))
        assert dlg.cheng_box.isEnabled()
        dlg.chk_cheng.setChecked(True)
        qapp.processEvents()
        assert dlg._cheng_fields.isVisible()
        assert len(dlg._assay_rows) == 1
        dlg._add_assay_btn.click()
        qapp.processEvents()
        assert len(dlg._assay_rows) == 2
        dlg.measure_combo.setCurrentIndex(dlg.measure_combo.findData("Ki"))
        qapp.processEvents()
        assert not dlg.cheng_box.isEnabled()
        assert not dlg.chk_cheng.isChecked()
        assert not dlg._cheng_fields.isVisible()
    finally:
        dlg.close()


def test_cheng_prusoff_request_reads_assay_concentrations(qapp) -> None:
    from molmanager.ui.dialogs.potency import PotencyStandardizationDialog

    dlg = PotencyStandardizationDialog(["IC50", "Km"], 0, unit_columns=["Unit"])
    dlg.show()
    qapp.processEvents()
    try:
        dlg.chk_p.setChecked(False)
        dlg.desired_unit.setCurrentIndex(dlg.desired_unit.findData("uM"))
        dlg.chk_cheng.setChecked(True)
        qapp.processEvents()
        row = dlg._assay_rows[0]
        row.conc_value.setText("10")
        row.ref_mode.setCurrentIndex(row.ref_mode.findData("column"))
        row.ref_column.setCurrentText("Km")
        qapp.processEvents()
        request = dlg.request()
        assert request is not None
        assert request.column == "IC50"
        assert request.unit_column == "Unit"
        assert request.desired_unit == "uM"
        assert request.write_p is False
        assert request.write_ki is True
        assert request.mw_column is None
        assert len(request.assay_concentrations) == 1
        term = request.assay_concentrations[0]
        assert term.conc_constant == 10
        assert term.conc_column is None
        assert term.ref_constant is None
        assert term.ref_column == "Km"
    finally:
        dlg.close()


def test_cheng_prusoff_rejects_a_nonpositive_km():
    assert cheng_prusoff_ki(1e-6, 1e-6, 0) is None
    assert parse_concentration("0", allow_zero=True) == 0
    assert parse_concentration("0") is None
