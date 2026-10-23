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

"""Calculate Descriptors Name tab stays on local identifiers."""

from __future__ import annotations

from PyQt5.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOptionTab, QWidget

from molmanager.descriptors.catalog import DESCRIPTOR_TAB_ORDER, iter_descriptor_tab_items
from molmanager.ui.dialogs.properties import PropertyDialog


def _painted_tab_positions(bar) -> dict[int, QStyleOptionTab.TabPosition]:
    """Tab index → shape position from the last paint. The end marker is private."""
    found: dict[int, QStyleOptionTab.TabPosition] = {}

    class _Probe(QProxyStyle):
        def drawControl(self, element, option, painter, widget=None):  # noqa: ANN001
            if element == QStyle.CE_TabBarTab and widget is bar:
                for index in range(bar.count()):
                    if bar.tabRect(index) == option.rect:
                        found[index] = option.position
                        break
            super().drawControl(element, option, painter, widget)

    probe = _Probe()
    bar.setStyle(probe)
    try:
        bar.repaint()
        QApplication.instance().processEvents()
    finally:
        bar.setStyle(None)
    return found


def test_property_dialog_name_tab_is_local_only(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=0)
    assert "Common Name" not in dlg.cbs
    assert "Synonyms" not in dlg.cbs
    assert dlg.cbs["SMILES String"][1] == "SMILES"
    assert dlg.cbs["InChI Key"][1] == "INCHIKEY"
    assert dlg.cbs["Molecular formula"][1] == "MOLFORMULA"
    dlg.cbs["SMILES String"][0].setChecked(True)
    dlg.cbs["InChI Key"][0].setChecked(True)
    disp, fns = dlg.get_selected()
    assert disp == ["SMILES String", "InChI Key"]
    assert fns == ["SMILES", "INCHIKEY"]
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


def test_descriptor_tabs_stay_even_when_another_tab_is_inserted(qapp) -> None:  # noqa: ARG001
    """The last tab must paint as the end tab, including after a mid-bar insert.

    Qt 5.15 otherwise keeps the previous end tab's shape, and Fusion draws an
    extra border before the real last tab (the Complexity / Electronic gap).
    """
    dlg = PropertyDialog(["Structure"], selected_row_count=0)
    try:
        dlg.show()
        qapp.processEvents()
        bar = dlg.tabs.tabBar()
        last = bar.count() - 1
        positions = _painted_tab_positions(bar)
        assert positions[last] == QStyleOptionTab.End
        assert positions[last - 1] == QStyleOptionTab.Middle

        dlg.tabs.insertTab(last, QWidget(), "Extra")
        qapp.processEvents()
        stale = _painted_tab_positions(bar)
        assert stale[last] == QStyleOptionTab.End
        assert stale[last + 1] == QStyleOptionTab.Middle

        dlg._repair_tab_bar_end_marker()
        qapp.processEvents()
        fixed = _painted_tab_positions(bar)
        assert fixed[bar.count() - 1] == QStyleOptionTab.End
        assert fixed[bar.count() - 2] == QStyleOptionTab.Middle
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
