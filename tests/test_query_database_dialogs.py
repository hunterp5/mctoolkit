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

"""PubChem and ChEMBL query dialogs list every field, with no Close button."""

from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox, QPushButton

from molmanager.sources.pubchem_vendors import VendorOffer
from molmanager.ui.external.chembl import ChEMBLDialog
from molmanager.ui.external.external_db import ExternalDBDialog
from molmanager.ui.external.patent_query import PatentQueryDialog
from molmanager.ui.external.pubchem import FIELD_COMMON_NAME, PubChemDialog
from molmanager.ui.external.query_form import MODE_IDENTITY, MODE_SIMILARITY
from molmanager.ui.external.vendors import VendorQueryDialog, VendorResult


def _button_labels(dialog) -> list[str]:
    return [button.text().replace("&", "") for button in dialog.findChildren(QPushButton)]


def test_pubchem_dialog_shows_every_field(qapp) -> None:
    dlg = PubChemDialog()
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.query_bar.mode.currentData() == MODE_IDENTITY
        assert dlg.query_bar.sim_row.isHidden()
        assert not hasattr(dlg, "field_preset")
        assert dlg.field_checks["CID"].isVisible()
        assert dlg.field_checks["CID"].isChecked()
        assert dlg.field_checks[FIELD_COMMON_NAME].isChecked()
        assert dlg.field_checks["IsomericSMILES"].isChecked()
        assert dlg.field_checks["MolecularWeight"].isVisible()
        assert not dlg.field_checks["MolecularWeight"].isChecked()
        assert dlg.field_checks["IUPAC"].text() == "IUPAC name"
        titles = {box.title() for box in dlg.findChildren(QGroupBox)}
        assert titles >= {"Identifiers / names", "Structures", "PhysChem", "Counts / topology"}
        assert "Close" not in _button_labels(dlg)

        dlg.query_bar.mode.setCurrentIndex(dlg.query_bar.mode.findData(MODE_SIMILARITY))
        assert not dlg.query_bar.sim_row.isHidden()
    finally:
        dlg.close()


def test_chembl_dialog_shows_properties_and_activity_box(qapp) -> None:
    dlg = ChEMBLDialog()
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.query_bar.mode.currentData() == MODE_IDENTITY
        assert dlg.query_bar.sim_row.isHidden()
        assert dlg.chk_identity.isVisible()
        assert dlg.chk_identity.isChecked()
        assert dlg.chk_structures.isChecked()
        assert not any(box.isChecked() for box in dlg.prop_checks.values())
        assert dlg.prop_checks["full_mwt"].isVisible()
        assert dlg.prop_checks["full_mwt"].text() == "Molecular Weight"
        titles = {box.title() for box in dlg.findChildren(QGroupBox)}
        assert "Properties" in titles
        assert "Activities and targets" in titles
        assert dlg.chk_bioactivity.isVisible()
        assert not dlg.chk_bioactivity.isChecked()
        assert dlg.spin_act.isVisible()
        assert dlg.spin_targ.isVisible()
        assert dlg.tabs.count() == 1
        assert dlg.tabs.tabText(0) == "Results"
        assert "Close" not in _button_labels(dlg)

        dlg._query_activities = True
        dlg._query_targets = False
        dlg._on_finished([], ["lookup ok"], "act", "")
        assert dlg.tabs.count() == 2
        assert dlg.tabs.tabText(1) == "Activities"
        assert "lookup ok" in dlg.out.toPlainText()
    finally:
        dlg.close()


def test_query_dialogs_have_no_close_button(qapp) -> None:  # noqa: ARG001
    dialogs = [
        PubChemDialog(),
        ChEMBLDialog(),
        VendorQueryDialog(),
        PatentQueryDialog(),
        ExternalDBDialog(),
    ]
    try:
        for dlg in dialogs:
            assert "Close" not in _button_labels(dlg)
    finally:
        for dlg in dialogs:
            dlg.close()


def test_vendor_dialog_omits_structures_with_no_products(qapp) -> None:  # noqa: ARG001
    dlg = VendorQueryDialog()
    try:
        assert dlg.query_bar.mode.isHidden()
        assert dlg.query_bar.sim_row.isHidden()
        assert not dlg.btn_add.isEnabled()
        dlg._on_finished([], ["C | no vendors"])
        assert not dlg.btn_add.isEnabled()
        assert dlg.tree.topLevelItemCount() == 0
        assert "no vendors" in dlg.out.toPlainText()
        assert "omitted" in dlg.status.text()

        offer = VendorOffer("CATO", "C1343073", "https://example.test/p")
        acetic = VendorResult(
            smiles="CC(=O)O",
            vendor=offer.vendor,
            product_id=offer.product_id,
            url=offer.url,
            fields=offer.as_fields(),
        )
        second = VendorResult(
            smiles="CCO",
            vendor="Other",
            product_id="E1",
            url="",
            fields={"Vendor": "Other", "Product ID": "E1", "URL": ""},
        )
        dlg._on_finished([acetic, second], ["CC(=O)O | CID=176 | 1 vendor(s)"])
        assert dlg.btn_add.isEnabled()
        assert dlg.tree.topLevelItemCount() == 2
        first = dlg.tree.topLevelItem(0)
        assert first is not None
        assert not first.isExpanded()
        assert first.text(0) == "CC(=O)O — 1 vendor"
        assert first.childCount() == 1
        child = first.child(0)
        assert child.text(0) == "CATO"
        assert child.text(1) == "C1343073"
        assert child.text(2) == "https://example.test/p"
        assert dlg.tree.topLevelItem(1).text(0) == "CCO — 1 vendor"

        dlg.tree.clear()
        dlg._last = []
        dlg._on_structure_done([acetic], "CC(=O)O | CID=176 | 1 vendor(s)")
        dlg._on_finished([], [])
        assert dlg.tree.topLevelItemCount() == 1
        arrived = dlg.tree.topLevelItem(0)
        assert arrived is not None and arrived.isExpanded()
        assert arrived.child(0).text(0) == "CATO"
    finally:
        dlg.close()
