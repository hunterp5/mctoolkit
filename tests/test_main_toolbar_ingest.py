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

"""Main menubar stays disabled while the table is loading."""

from __future__ import annotations

from PyQt5.QtCore import Qt

from molmanager.ui.main_window import ChemistryWorkspaceWindow


def test_main_toolbar_disabled_while_ingest_loading(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    file_menu = next(a.menu() for a in mb.actions() if a.menu() is not None)

    assert file_menu.isEnabled()
    assert w._btn_workspace_layout.isEnabled()
    assert w._btn_processes.isEnabled()
    assert w._help_menu.isEnabled()

    w._set_ingest_loading(True)
    assert not file_menu.isEnabled()
    assert not w._btn_workspace_layout.isEnabled()
    assert w._btn_processes.isEnabled()
    assert w._btn_processes.text() == "Log"
    assert not w._help_menu.isEnabled()
    assert not w._act_user_guide.isEnabled()
    assert not w._act_citations.isEnabled()

    w._set_ingest_loading(False)
    assert file_menu.isEnabled()
    assert w._btn_workspace_layout.isEnabled()
    assert w._btn_processes.isEnabled()
    assert w._help_menu.isEnabled()
    w.close()


def test_help_is_last_item_in_settings_menu(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    labels = [a.text().replace("&", "") for a in mb.actions() if a.text()]
    assert labels[-1] == "Settings"
    settings = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Settings")
    settings_labels = [a.text().replace("&", "") for a in settings.actions() if a.text()]
    assert settings_labels[-1] == "Help"
    menu = w._help_menu
    assert menu is not None
    assert menu.menuAction() in settings.actions()
    item_labels = [a.text().replace("&", "") for a in menu.actions()]
    assert item_labels == ["User Guide", "Citations"]
    assert w._act_user_guide in menu.actions()
    assert w._act_citations in menu.actions()
    corner = mb.cornerWidget(Qt.TopRightCorner)
    ly = corner.layout()
    widgets = [ly.itemAt(i).widget() for i in range(ly.count())]
    assert widgets == [w._btn_workspace_layout, w._btn_processes]
    w.close()


def test_main_window_table_sits_flush_under_menubar(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    ly = w.centralWidget().layout()
    m = ly.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0)
    assert ly.spacing() == 0
    w.close()
