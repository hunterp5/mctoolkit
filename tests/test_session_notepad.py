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

"""Floating session notepad: chrome, formatting, font isolation, and restore."""

from __future__ import annotations

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QFont, QPalette, QTextCharFormat, QTextCursor, QTextListFormat
from PyQt5.QtWidgets import QLabel
from rdkit import Chem
from session_roundtrip import open_saved, saved_document

from molmanager.ui.dockable_plot_glyphs import FORMAT_GLYPH_BTN_SIZE, FORMAT_GLYPH_ICON_SIZE
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.session_notepad import (
    DEFAULT_NOTE_COLOR,
    DEFAULT_NOTE_PT,
    NotepadDialog,
)
from molmanager.ui.theme import palette_for_theme


@pytest.fixture(autouse=True)
def _skip_session_auto_render(monkeypatch) -> None:
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )


def _tools_menu(window: ChemistryWorkspaceWindow):
    bar = window.menuBar()
    return next(act.menu() for act in bar.actions() if act.text().replace("&", "") == "Tools")


def _document_format(panel):
    cursor = panel._edit.textCursor()
    cursor.select(QTextCursor.Document)
    return cursor.charFormat()


def test_utilities_menu_opens_floating_notepad(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    action = next(
        act for act in _tools_menu(window).actions() if act.text().replace("&", "") == "Notepad"
    )
    action.trigger()
    host = window.session_notepad
    dialog = host.dialog
    panel = host.panel
    assert isinstance(dialog, NotepadDialog)
    assert panel is dialog._panel
    assert not dialog.isHidden()
    assert dialog.windowTitle() == "Notepad"
    assert panel.color_hex() == "#000000"
    assert panel._edit.placeholderText() == ""
    assert not panel._is_docked_in_main_window()
    assert not panel._add_to_main_btn.isHidden()
    assert panel._send_window_btn.isHidden()
    assert panel._close_btn.isHidden()
    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert "Color" not in labels
    for btn in (
        panel._bold,
        panel._italic,
        panel._underline,
        panel._color_btn,
        panel._subscript,
        panel._superscript,
        panel._bullet,
        panel._number,
    ):
        assert btn.text() == ""
        assert not btn.icon().isNull()
        assert btn.width() == FORMAT_GLYPH_BTN_SIZE
        assert btn.iconSize().width() == FORMAT_GLYPH_ICON_SIZE
    assert panel._bold.toolTip() == "Bold"
    assert panel._italic.toolTip() == "Italic"
    assert panel._underline.toolTip() == "Underline"
    assert panel._color_btn.toolTip() == "Text color"
    assert panel._subscript.toolTip() == "Subscript"
    assert panel._superscript.toolTip() == "Superscript"
    assert panel._bullet.toolTip() == "Bulleted list"
    assert panel._number.toolTip() == "Numbered list"

    panel.set_text("check the amide series")
    dialog.close()
    assert dialog.isHidden()
    assert panel.text() == "check the amide series"
    window.open_notepad()
    assert not dialog.isHidden()
    assert panel.text() == "check the amide series"
    window.close()


def test_new_notepad_types_black_text(qapp):
    previous = QPalette(qapp.palette())
    qapp.setPalette(palette_for_theme("dark"))
    window = ChemistryWorkspaceWindow()
    try:
        window.open_notepad()
        panel = window.session_notepad.panel
        caret = panel._edit.currentCharFormat()
        assert caret.foreground().style() != Qt.NoBrush
        assert caret.foreground().color().name() == "#000000"
        panel._edit.insertPlainText("new note")
        typed = _document_format(panel)
        assert typed.foreground().style() != Qt.NoBrush
        assert typed.foreground().color().name() == "#000000"
    finally:
        window.close()
        qapp.setPalette(previous)


def test_notepad_format_glyphs_apply_to_selection(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    window.open_notepad()
    panel = window.session_notepad.panel
    assert panel is not None
    panel.set_text("abc")
    cursor = panel._edit.textCursor()
    cursor.select(QTextCursor.Document)
    panel._edit.setTextCursor(cursor)
    panel._bold.click()
    panel._italic.click()
    panel._underline.click()
    fmt = _document_format(panel)
    assert fmt.fontWeight() >= QFont.Bold
    assert fmt.fontItalic()
    assert fmt.fontUnderline()
    assert panel._bold.isChecked()
    assert panel._italic.isChecked()
    assert panel._underline.isChecked()

    panel._subscript.click()
    assert _document_format(panel).verticalAlignment() == QTextCharFormat.AlignSubScript
    assert panel._subscript.isChecked()
    panel._superscript.click()
    assert _document_format(panel).verticalAlignment() == QTextCharFormat.AlignSuperScript
    assert panel._superscript.isChecked()
    assert not panel._subscript.isChecked()
    panel._superscript.click()
    assert _document_format(panel).verticalAlignment() == QTextCharFormat.AlignNormal

    panel.set_text("one\ntwo")
    cursor = panel._edit.textCursor()
    cursor.select(QTextCursor.Document)
    panel._edit.setTextCursor(cursor)
    panel._bullet.click()
    first = panel._edit.document().begin()
    assert first.textList() is not None
    assert first.textList().format().style() == QTextListFormat.ListDisc
    assert first.next().textList().format().style() == QTextListFormat.ListDisc
    assert panel._bullet.isChecked()
    panel._number.click()
    first = panel._edit.document().begin()
    assert first.textList().format().style() == QTextListFormat.ListDecimal
    assert panel._number.isChecked()
    assert not panel._bullet.isChecked()
    panel._number.click()
    assert panel._edit.document().begin().textList() is None

    panel.set_color(QColor("#aa1133"))
    colored = _document_format(panel)
    assert colored.foreground().color().name() == "#aa1133"
    assert panel.color_hex() == "#aa1133"
    window.close()


def test_notepad_font_ignores_application_font(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    window.open_notepad()
    panel = window.session_notepad.panel
    assert panel is not None
    panel.set_text("note")
    panel.set_font_pt(22)
    panel.set_color(QColor("#aa1133"))
    previous = int(window._app_font_pt)
    window._set_app_font_pt(9, persist=False)
    qapp.sendEvent(panel._edit, QEvent(QEvent.ApplicationFontChange))
    qapp.processEvents()
    try:
        assert panel.font_pt() == 22
        assert panel._edit.font().pointSize() == 22
        assert panel.color_hex() == "#aa1133"
        sheet = panel._edit.styleSheet()
        assert "22pt" not in sheet
        assert "9pt" not in sheet
        assert "#aa1133" not in sheet
        assert _document_format(panel).foreground().color().name() == "#aa1133"
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
    panel = window.session_notepad.panel
    assert panel is not None
    panel.set_text("assay notes\nsecond line")
    panel.set_font_pt(18)
    panel.set_color(QColor("#003366"))

    doc = saved_document(window)
    assert doc["notepad"]["text"] == "assay notes\nsecond line"
    assert doc["notepad"]["font_pt"] == 18
    assert doc["notepad"]["color"] == "#003366"
    assert doc["notepad"]["visible"] is True
    assert doc["notepad"]["docked"] is False
    assert "003366" in doc["notepad"]["html"].lower()
    selected = saved_document(window, oids={0})
    assert selected["notepad"]["text"] == "assay notes\nsecond line"

    restored = ChemistryWorkspaceWindow()
    open_saved(window, restored)
    restored_panel = restored.session_notepad.panel
    restored_dialog = restored.session_notepad.dialog
    assert restored_panel is not None
    assert isinstance(restored_dialog, NotepadDialog)
    assert restored_panel.text() == "assay notes\nsecond line"
    assert restored_panel.font_pt() == 18
    assert restored_panel.color_hex() == "#003366"
    assert not restored_dialog.isHidden()
    assert restored_panel._edit.font().pointSize() == 18
    assert _document_format(restored_panel).foreground().color().name() == "#003366"

    restored.clear_all()
    assert restored_panel.text() == ""
    assert restored_panel.font_pt() == DEFAULT_NOTE_PT
    assert restored_panel.color_hex() == DEFAULT_NOTE_COLOR
    assert restored_dialog.isHidden()
    assert restored.collect_notepad_session() is None
    window.close()
    restored.close()


def test_notepad_docks_like_a_browser_and_close_keeps_notes(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    window.open_notepad()
    panel = window.session_notepad.panel
    assert panel is not None
    panel.set_text("keep me")
    panel._add_to_main_window()
    assert window.is_plot_docked(panel)
    assert not panel._send_window_btn.isHidden()
    assert not panel._close_btn.isHidden()
    assert panel._add_to_main_btn.isHidden()
    panel._close_btn.click()
    assert not window.is_plot_docked(panel)
    assert panel.text() == "keep me"
    window.open_notepad()
    dialog = window.session_notepad.dialog
    assert isinstance(dialog, NotepadDialog)
    assert dialog._panel is panel
    assert not dialog.isHidden()
    assert not panel._is_docked_in_main_window()
    assert panel.text() == "keep me"
    window.close()
