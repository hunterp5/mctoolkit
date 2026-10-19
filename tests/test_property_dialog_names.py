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

"""Calculate Descriptors Name tab includes PubChem lookups."""

from __future__ import annotations

from molmanager.descriptors.catalog import DESCRIPTOR_TAB_ORDER, iter_descriptor_tab_items
from molmanager.ui.dialogs.properties import PropertyDialog


def test_property_dialog_name_tab_includes_common_name_and_synonyms(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=0)
    assert "Common Name" in dlg.cbs
    assert "Synonyms" in dlg.cbs
    assert dlg.cbs["Common Name"][1] == "COMMON_NAME"
    assert dlg.cbs["Synonyms"][1] == "SYNONYMS"
    assert "PubChem" in dlg.cbs["Common Name"][0].toolTip()
    dlg.cbs["Common Name"][0].setChecked(True)
    dlg.cbs["Synonyms"][0].setChecked(True)
    disp, fns = dlg.get_selected()
    assert disp == ["Common Name", "Synonyms"]
    assert fns == ["COMMON_NAME", "SYNONYMS"]
    dlg.close()


def test_property_dialog_opens_wide_enough_for_every_tab(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure"], selected_row_count=0)
    try:
        bar = dlg.tabs.tabBar()
        margins = dlg.layout().contentsMargins()
        needed = bar.sizeHint().width() + margins.left() + margins.right()
        assert dlg.minimumWidth() >= needed
        assert dlg.width() >= dlg.minimumWidth()
        dlg.show()
        qapp.processEvents()
        last = bar.tabRect(bar.count() - 1)
        assert last.right() <= bar.width()
        assert last.left() >= 0
        labels = [bar.tabText(i) for i in range(bar.count())]
        atom = labels.index("Atom Counts")
        complexity = labels.index("Complexity")
        assert complexity == atom + 1
        dlg.resize(dlg.width() + 120, dlg.height())
        qapp.processEvents()
        gap = bar.tabRect(complexity).left() - bar.tabRect(atom).right()
        assert gap <= 2
    finally:
        dlg.close()


def test_property_dialog_checkboxes_match_catalog(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure"], selected_row_count=0)
    tabs = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    catalog = iter_descriptor_tab_items()
    ordered = list(DESCRIPTOR_TAB_ORDER)
    ordered.insert(ordered.index("Drug-likeness") + 1, "Structural Alerts")
    assert tabs == ordered
    expected = {disp: key for _tab, items in catalog for disp, key in items}
    assert {disp: internal for disp, (_cb, internal) in dlg.cbs.items()} == expected
    dlg.close()
