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

"""Physical properties helpers for the sketcher View panel."""

from __future__ import annotations

import threading

from PyQt5.QtCore import QThreadPool
from PyQt5.QtWidgets import QMenuBar, QWidget
from rdkit import Chem

from molmanager.ui.sketcher.constants import (
    ELEMENT_FAMILY_GROUPS,
    SKETCH_ELEMENT_SYMBOLS,
)
from molmanager.ui.sketcher.customize_elements import (
    element_groups_for_symbols,
    normalize_toolbar_element_symbols,
)
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.physical_properties import (
    compute_rdkit_physical_properties,
    compute_sketch_physical_properties,
)


def test_compute_rdkit_physical_properties_ethanol() -> None:
    mol = Chem.MolFromSmiles("CCO")
    props = compute_rdkit_physical_properties(mol)
    assert props.error is None
    assert props.mw is not None and abs(props.mw - 46.069) < 0.05
    assert props.tpsa is not None and props.tpsa > 15.0
    assert props.logp is not None
    assert props.qed is not None and 0.0 <= props.qed <= 1.0
    assert props.ro5_pass == "Yes"
    assert props.ro5_violations == 0
    assert props.logd is None
    assert props.pka_values is None


def test_compute_rdkit_physical_properties_empty() -> None:
    props = compute_rdkit_physical_properties(None)
    assert props.error == "empty"


def test_compute_ionization_failure_when_no_microstates(monkeypatch) -> None:
    monkeypatch.setattr(
        "molmanager.ui.sketcher.physical_properties.predict_microstates_for_sketch",
        lambda _mol, cancel_event=None: None,
    )
    mol = Chem.MolFromSmiles("CCN")
    props = compute_sketch_physical_properties(mol, with_ionization=True)
    assert props.mw is not None
    assert props.error == "pKa calculation failed"
    assert props.logd is None
    assert props.pka_values is None
    assert props.ab_mps is None
    assert props.cns_mpo is None


def test_compute_ionization_properties_raises_without_microstates(monkeypatch) -> None:
    from molmanager.ui.sketcher.physical_properties import compute_ionization_properties

    monkeypatch.setattr(
        "molmanager.ui.sketcher.physical_properties.predict_microstates_for_sketch",
        lambda _mol, cancel_event=None: None,
    )
    mol = Chem.MolFromSmiles("CCO")
    try:
        compute_ionization_properties(mol)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "pKa" in str(exc)


def test_normalize_toolbar_element_symbols() -> None:
    out = normalize_toolbar_element_symbols(["au", "C", "N", "C"])
    assert out[0] == "C"
    assert "N" in out
    assert "Au" in out
    assert out.count("C") == 1


def test_element_groups_for_symbols_by_family() -> None:
    groups = dict(element_groups_for_symbols(["C", "Au", "N", "Rb", "Gd", "Sn"]))
    assert groups["Carbon Group"] == ("C", "Sn")
    assert groups["Pnictogens"] == ("N",)
    assert groups["Alkali Metals"] == ("Rb",)
    assert groups["Transition Metals"] == ("Au",)
    assert groups["Lanthanides"] == ("Gd",)
    assert "Other" not in groups


def test_element_family_groups_cover_sketch_symbols() -> None:
    covered = {sym for _title, syms in ELEMENT_FAMILY_GROUPS for sym in syms}
    assert set(SKETCH_ELEMENT_SYMBOLS) == covered


def test_physical_properties_view_action(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    bars = dlg.findChildren(QMenuBar)
    assert bars
    menus = {a.text(): a.menu() for a in bars[0].actions() if a.menu()}
    assert "Physical Properties" in [a.text() for a in menus["View"].actions() if a.text()]
    assert "Customize Elements" in [a.text() for a in menus["Settings"].actions() if a.text()]
    dlg._open_physical_properties()
    assert dlg._phys_props_dlg is not None
    assert dlg._phys_props_dlg.isVisible()
    assert not hasattr(dlg._phys_props_dlg, "_val_smiles")
    dlg._phys_props_dlg.close()
    qapp.processEvents()
    dlg.close()


def test_closing_physical_properties_survives_a_late_ionization_report(qapp, monkeypatch) -> None:
    """The background pKa job must not emit on the window after it has been destroyed."""
    from molmanager.ui.sketcher.physical_properties import (
        _IonizationSignals,
        _IonizationWorker,
    )

    def _cancelled(mol, cancel_event=None):  # noqa: ARG001
        raise ValueError("cancelled")

    monkeypatch.setattr(
        "molmanager.ui.sketcher.physical_properties.compute_ionization_properties",
        _cancelled,
    )
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    signals = _IonizationSignals()
    worker = _IonizationWorker(mol, 1, signals, threading.Event())
    signals.deleteLater()
    qapp.processEvents()
    worker.run()

    dlg = SketcherDialog(QWidget())
    dlg.show()
    qapp.processEvents()
    assert dlg.canvas.load_from_rdkit_mol(mol)
    dlg._open_physical_properties()
    props = dlg._phys_props_dlg
    assert props is not None
    props._refresh_now()
    props.close()
    qapp.processEvents()
    QThreadPool.globalInstance().waitForDone(3000)
    qapp.processEvents()
    assert dlg._phys_props_dlg is None or not dlg._phys_props_dlg.isVisible()
    dlg._open_physical_properties()
    reopened = dlg._phys_props_dlg
    assert reopened is not None
    assert reopened.isVisible()
    assert reopened._shutting_down is False
    reopened.close()
    dlg.close()


def test_populate_element_toolbar_subset(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.sketcher.constants import SKETCH_RAIL_ELEMENTS

    dlg = SketcherDialog(QWidget())
    dlg._populate_element_toolbar(["C", "N", "O", "Au"])
    assert list(dlg._element_btn_by_symbol) == list(SKETCH_RAIL_ELEMENTS)
    assert dlg._more_element_symbols == ["Au"]
    assert dlg.tb_wildcard is not None
    assert dlg.tb_any_element is not None
    groups = dict(element_groups_for_symbols(["C", "N", "O", "Au"]))
    assert groups["Transition Metals"] == ("Au",)
    dlg.close()
