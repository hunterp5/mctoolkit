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

"""Calculate Descriptors checkbox tooltips and citation-free layout."""

from __future__ import annotations

from molmanager.reference.descriptor_tooltips import descriptor_checkbox_tooltip
from molmanager.chem.rdkit_fingerprints import FINGERPRINT_SPECS
from molmanager.ui.dialogs.properties import PropertyDialog


def test_descriptor_checkbox_tooltip_covers_common_keys() -> None:
    assert "sp3" in descriptor_checkbox_tooltip("FractionCSP3").lower()
    assert "pH 7.4" in descriptor_checkbox_tooltip("LOGD74")
    assert "canonical" in descriptor_checkbox_tooltip("SMILES").lower()
    assert "3D" in descriptor_checkbox_tooltip("PMI1")
    assert "GFN2" in descriptor_checkbox_tooltip("HOMO")
    assert "LUMO" in descriptor_checkbox_tooltip("HOMO_LUMO_GAP")
    assert "carbon" in descriptor_checkbox_tooltip("Count_C")
    assert descriptor_checkbox_tooltip("") == ""
    assert descriptor_checkbox_tooltip("not_a_real_descriptor") == ""


def test_descriptor_checkbox_tooltip_covers_fingerprint_specs() -> None:
    for spec in FINGERPRINT_SPECS:
        tip = descriptor_checkbox_tooltip(spec.internal_key)
        assert tip, spec.internal_key
        assert "on-bit" in tip.lower() or "count" in tip.lower()


def test_every_descriptor_checkbox_has_a_tooltip(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=0)
    missing = [
        f"{disp} ({internal})"
        for disp, (cb, internal) in dlg.cbs.items()
        if not str(cb.toolTip() or "").strip()
    ]
    dlg.close()
    assert missing == []


def test_property_dialog_has_no_inline_citation_labels(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel

    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=0)
    cites = [lbl for lbl in dlg.findChildren(QLabel) if lbl.openExternalLinks()]
    dlg.close()
    assert cites == []
