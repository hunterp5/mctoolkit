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

"""Dockable session notepad: font isolation and session restore."""

from __future__ import annotations

import pytest
from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QColor
from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.session_notepad import DEFAULT_NOTE_COLOR, DEFAULT_NOTE_PT


@pytest.fixture(autouse=True)
def _skip_session_auto_render(monkeypatch) -> None:
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )


def _utilities_menu(window: ChemistryWorkspaceWindow):
    bar = window.menuBar()
    tools = next(act.menu() for act in bar.actions() if act.text().replace("&", "") == "Tools")
    return next(
        act.menu()
        for act in tools.actions()
        if act.menu() and act.text().replace("&", "") == "Utilities"
    )


def test_utilities_menu_opens_notepad(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    action = next(
        act for act in _utilities_menu(window).actions() if act.text().replace("&", "") == "Notepad"
    )
    action.trigger()
    dock = window.session_notepad.dock
    assert dock is not None
    assert not dock.isHidden()
    assert window.dockWidgetArea(dock) != 0
    dock.set_text("check the amide series")
    dock.close()
    assert dock.isHidden()
    assert dock.text() == "check the amide series"
    window.open_notepad()
    assert not dock.isHidden()
    assert dock.text() == "check the amide series"
    window.close()


def test_notepad_font_ignores_application_font(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    window.open_notepad()
    dock = window.session_notepad.dock
    assert dock is not None
    dock.set_font_pt(22)
    dock.set_color(QColor("#aa1133"))
    previous = int(window._app_font_pt)
    window._set_app_font_pt(9, persist=False)
    qapp.sendEvent(dock._edit, QEvent(QEvent.ApplicationFontChange))
    qapp.processEvents()
    try:
        assert dock.font_pt() == 22
        assert dock._edit.font().pointSize() == 22
        sheet = dock._edit.styleSheet()
        assert "22pt" in sheet
        assert "#aa1133" in sheet
        assert window._app_font_pt == 9
    finally:
        window._set_app_font_pt(previous, persist=False)
        window.close()


def test_session_roundtrip_restores_notepad(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    window.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(0, {"SMILES": "C"})
    window.mols[0] = Chem.MolFromSmiles("C")
    window.next_oid = 1
    window.open_notepad()
    dock = window.session_notepad.dock
    assert dock is not None
    dock.set_text("assay notes\nsecond line")
    dock.set_font_pt(18)
    dock.set_color(QColor("#003366"))

    doc = window._build_session_document()
    assert doc["notepad"]["text"] == "assay notes\nsecond line"
    assert doc["notepad"]["font_pt"] == 18
    assert doc["notepad"]["color"] == "#003366"
    assert doc["notepad"]["visible"] is True
    selected = window._build_session_document(oids={0})
    assert selected["notepad"]["text"] == "assay notes\nsecond line"

    restored = ChemistryWorkspaceWindow()
    restored._apply_session_document(doc)
    restored_dock = restored.session_notepad.dock
    assert restored_dock is not None
    assert restored_dock.text() == "assay notes\nsecond line"
    assert restored_dock.font_pt() == 18
    assert restored_dock.color_hex() == "#003366"
    assert not restored_dock.isHidden()
    assert "18pt" in restored_dock._edit.styleSheet()

    restored.clear_all()
    assert restored_dock.text() == ""
    assert restored_dock.font_pt() == DEFAULT_NOTE_PT
    assert restored_dock.color_hex() == DEFAULT_NOTE_COLOR
    assert restored_dock.isHidden()
    assert restored.collect_notepad_session() is None
    window.close()
    restored.close()
