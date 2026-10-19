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

"""Potency unit conversion and Cheng–Prusoff Ki. No Qt."""

from __future__ import annotations

import math

from molmanager.chem.potency import (
    cheng_prusoff_ki,
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


def test_standardize_writes_molar_and_pIC50():
    cells = standardize_activity(
        "100",
        unit="nM",
        measure="IC50",
        write_molar=True,
        write_p=True,
    )
    assert cells == {"IC50 (M)": "1e-07", "pIC50": "7.000"}


def test_censored_and_nonpositive_values_stay_blank():
    for text in ("", "  ", ">10000", "<1", "~5", "n.d.", "0", "-3"):
        cells = standardize_activity(
            text,
            unit="nM",
            measure="Ki",
            write_molar=True,
            write_p=True,
        )
        assert cells == {"Ki (M)": "", "pKi": ""}, text


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
        write_molar=False,
        write_p=False,
        write_ki=True,
        substrate_molar=km,
        km_molar=km,
    )
    assert cells["Ki (M)"] == "5e-08"
    assert cells["pKi"] == "7.301"


def test_cheng_prusoff_controls_follow_the_ic50_measure(qapp) -> None:
    from molmanager.ui.dialogs.potency import PotencyStandardizationDialog

    dlg = PotencyStandardizationDialog(["IC50"], 0)
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.measure_combo.currentData() == "IC50"
        assert dlg.cheng_box.isEnabled()
        dlg.chk_cheng.setChecked(True)
        assert dlg._cheng_fields.isVisible()
        dlg.measure_combo.setCurrentIndex(dlg.measure_combo.findData("Ki"))
        qapp.processEvents()
        assert not dlg.cheng_box.isEnabled()
        assert not dlg.chk_cheng.isChecked()
        assert not dlg._cheng_fields.isVisible()
    finally:
        dlg.close()


def test_cheng_prusoff_rejects_a_nonpositive_km():
    assert cheng_prusoff_ki(1e-6, 1e-6, 0) is None
    assert parse_concentration("0", allow_zero=True) == 0
    assert parse_concentration("0") is None
