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

from __future__ import annotations

from molmanager.ui.theme import (
    THEME_CUSTOM,
    THEME_DARK,
    THEME_GROOVY,
    THEME_LIGHT,
    current_theme_name,
    default_app_font_pt,
    delete_custom_theme,
    filter_card_stylesheet,
    list_custom_theme_names,
    load_custom_theme_colors,
    load_saved_custom_palette_colors,
    load_saved_theme_name,
    make_custom_theme_id,
    palette_for_theme,
    save_custom_palette_colors,
    save_custom_theme,
    save_theme_name,
)


def _isolate_theme_settings(tmp_path, monkeypatch) -> None:
    """Point theme QSettings at a temp INI so tests do not touch the real profile."""
    from PyQt5.QtCore import QSettings

    ini = str(tmp_path / "molmanager_theme_test.ini")
    monkeypatch.setattr(
        "molmanager.ui.theme.QSettings",
        lambda *_a, **_k: QSettings(ini, QSettings.IniFormat),
    )


def test_theme_save_and_load(tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    assert load_saved_theme_name() == THEME_LIGHT
    save_theme_name(THEME_DARK)
    assert load_saved_theme_name() == THEME_DARK
    save_theme_name(THEME_LIGHT)
    assert load_saved_theme_name() == THEME_LIGHT
    save_theme_name(THEME_GROOVY)
    assert load_saved_theme_name() == THEME_GROOVY
    # Legacy "custom" with no named themes falls back to light.
    save_theme_name(THEME_CUSTOM)
    assert load_saved_theme_name() == THEME_LIGHT
    save_custom_theme("Ocean", {"window": "#112233"})
    save_theme_name(THEME_CUSTOM)
    assert load_saved_theme_name() == make_custom_theme_id("Ocean")
    save_theme_name(make_custom_theme_id("Ocean"))
    assert load_saved_theme_name() == make_custom_theme_id("Ocean")


def test_filter_card_stylesheet_uses_palette_roles():
    qss = filter_card_stylesheet()
    qss_l = qss.lower()
    assert "palette(base)" in qss_l
    assert "QFrame#FilterCard" in qss
    assert "background-color: transparent" in qss_l
    assert "border-bottom: 1px solid palette(mid)" in qss_l
    assert "border-radius: 0px" in qss_l
    assert 'fcDragging="true"' in qss
    assert "QPushButton#fcToggle" in qss
    assert 'QPushButton#fcToggle[fcActive="true"]' in qss
    # Same rules for both themes — colors come from the application palette.
    assert filter_card_stylesheet(THEME_LIGHT) == filter_card_stylesheet(THEME_DARK)
    assert filter_card_stylesheet(THEME_GROOVY) == filter_card_stylesheet(THEME_LIGHT)


def test_apply_application_theme_sets_current(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.theme import apply_application_theme

    apply_application_theme(QApplication.instance(), THEME_DARK)
    assert current_theme_name() == THEME_DARK
    apply_application_theme(QApplication.instance(), THEME_LIGHT)
    assert current_theme_name() == THEME_LIGHT
    apply_application_theme(QApplication.instance(), THEME_GROOVY)
    assert current_theme_name() == THEME_GROOVY
    name = save_custom_theme("ApplyMe", {"window": "#445566"})
    tid = make_custom_theme_id(name)
    apply_application_theme(QApplication.instance(), tid)
    assert current_theme_name() == tid


def test_status_bar_font_pt_is_one_point_below_app():
    from molmanager.ui.theme import MIN_FONT_PT, status_bar_font_pt

    assert status_bar_font_pt(10) == 9
    assert status_bar_font_pt(None) == 9
    assert status_bar_font_pt(8) == MIN_FONT_PT
    assert status_bar_font_pt(32) == 31


def test_table_text_alignment_save_load_and_flags(tmp_path, monkeypatch):
    from PyQt5.QtCore import Qt

    _isolate_theme_settings(tmp_path, monkeypatch)
    from molmanager.ui.theme import (
        load_saved_table_text_alignment,
        set_table_text_alignment,
        table_text_alignment,
        table_text_alignment_flags,
        table_text_alignment_label,
    )

    assert load_saved_table_text_alignment() == ("left", "center")
    assert table_text_alignment_label("right", "top") == "top right"
    assert table_text_alignment_label("left", "center") == "center left"
    assert table_text_alignment_label("center", "center") == "center"
    h, v = set_table_text_alignment("right", "up", persist=True)
    assert (h, v) == ("right", "top")
    assert load_saved_table_text_alignment() == ("right", "top")
    assert table_text_alignment() == ("right", "top")
    assert table_text_alignment_flags() == int(Qt.AlignRight | Qt.AlignTop)
    set_table_text_alignment("left", "center", persist=False)


def test_font_dialog_alignment_grid(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.font_settings import FontSettingsDialog

    dlg = FontSettingsDialog(10, 10, current_align_h="right", current_align_v="top")
    assert dlg.selected_table_alignment() == ("right", "top")
    assert dlg._align_buttons[("right", "top")].isChecked()
    dlg._align_buttons[("center", "center")].setChecked(True)
    assert dlg.selected_table_alignment() == ("center", "center")
    dlg._reset_default()
    assert dlg.selected_table_alignment() == ("left", "center")
    dlg.close()


def test_status_bar_visible_save_and_load(tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from molmanager.ui.theme import load_status_bar_visible, save_status_bar_visible

    assert load_status_bar_visible() is True
    save_status_bar_visible(False)
    assert load_status_bar_visible() is False
    save_status_bar_visible(True)
    assert load_status_bar_visible() is True


def test_custom_palette_save_load_and_apply(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from PyQt5.QtGui import QPalette
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.theme import (
        apply_application_theme,
        default_custom_palette_colors,
    )

    defaults = default_custom_palette_colors()
    assert "window" in defaults and defaults["window"].startswith("#")
    custom = dict(defaults)
    custom["window"] = "#112233"
    custom["highlight"] = "#aabbcc"
    saved = save_custom_palette_colors(custom)
    assert saved["window"].lower() == "#112233"
    loaded = load_saved_custom_palette_colors()
    assert loaded["window"].lower() == "#112233"
    assert loaded["highlight"].lower() == "#aabbcc"
    # Legacy save must not invent a named menu theme.
    assert list_custom_theme_names() == []
    tid = make_custom_theme_id("Mine")
    save_custom_theme("Mine", saved)
    pal = palette_for_theme(tid)
    assert pal.color(QPalette.Window).name().lower() == "#112233"
    apply_application_theme(QApplication.instance(), tid)
    assert current_theme_name() == tid
    assert QApplication.instance().palette().color(QPalette.Window).name().lower() == "#112233"


def test_named_custom_themes_save_switch_delete(tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)

    a = save_custom_theme("Alpha", {"window": "#111111"})
    b = save_custom_theme("Beta", {"window": "#222222"})
    assert list_custom_theme_names() == ["Alpha", "Beta"]
    assert load_custom_theme_colors("Alpha")["window"].lower() == "#111111"
    assert load_custom_theme_colors(make_custom_theme_id("Beta"))["window"].lower() == "#222222"
    save_theme_name(make_custom_theme_id(a))
    assert load_saved_theme_name() == make_custom_theme_id("Alpha")
    assert delete_custom_theme(b) is True
    assert list_custom_theme_names() == ["Alpha"]
    assert delete_custom_theme("Missing") is False


def test_both_themes_use_fusion_without_global_stylesheet(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.theme import apply_application_theme

    app = QApplication.instance()
    save_custom_theme("FusionCustom", {"window": "#abcdef"})
    for theme in (
        THEME_LIGHT,
        THEME_DARK,
        THEME_GROOVY,
        make_custom_theme_id("FusionCustom"),
    ):
        apply_application_theme(app, theme)
        assert app.style().objectName().lower() == "fusion"
        assert app.styleSheet() == ""


def test_group_boxes_follow_theme_without_global_stylesheet(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from PyQt5.QtWidgets import QApplication, QGroupBox

    from molmanager.ui.qt_widget_utils import group_box_stylesheet_for, install_group_box_style
    from molmanager.ui.theme import apply_application_theme

    app = QApplication.instance()
    install_group_box_style(app)
    titled = QGroupBox("Activity")
    untitled = QGroupBox()
    titled.ensurePolished()
    untitled.ensurePolished()
    assert "QGroupBox::title" in titled.styleSheet()
    assert titled.styleSheet() == group_box_stylesheet_for(titled)
    assert "QGroupBox::title" not in untitled.styleSheet()
    assert untitled.styleSheet() == group_box_stylesheet_for(untitled)
    light = titled.styleSheet()
    apply_application_theme(app, THEME_DARK)
    assert app.styleSheet() == ""
    assert titled.styleSheet() != light
    assert titled.styleSheet() == group_box_stylesheet_for(titled)
    assert untitled.styleSheet() == group_box_stylesheet_for(untitled)
    apply_application_theme(app, THEME_LIGHT)
    titled.deleteLater()
    untitled.deleteLater()


def test_groovy_palette_is_randomized():
    import random

    a = palette_for_theme(THEME_GROOVY, rng=random.Random(1))
    b = palette_for_theme(THEME_GROOVY, rng=random.Random(2))
    from PyQt5.QtGui import QPalette

    assert a.color(QPalette.Window) != b.color(QPalette.Window) or a.color(
        QPalette.Highlight
    ) != b.color(QPalette.Highlight)


def test_refresh_open_windows_theme_calls_hook(qapp):
    from PyQt5.QtWidgets import QApplication, QDialog

    from molmanager.ui.theme import apply_application_theme, refresh_open_windows_theme

    class _ThemeDlg(QDialog):
        def __init__(self):
            super().__init__()
            self.refreshed = 0

        def refresh_theme(self) -> None:
            self.refreshed += 1

    dlg = _ThemeDlg()
    dlg.show()
    apply_application_theme(QApplication.instance(), THEME_DARK)
    assert dlg.refreshed >= 1
    before = dlg.refreshed
    refresh_open_windows_theme(QApplication.instance())
    assert dlg.refreshed == before + 1
    dlg.close()


def test_application_theme_updates_table_header_palette(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from PyQt5.QtGui import QPalette
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.theme import apply_application_theme

    w = ChemistryWorkspaceWindow()
    apply_application_theme(QApplication.instance(), THEME_LIGHT)
    light = QApplication.instance().palette().color(QPalette.Button)
    apply_application_theme(QApplication.instance(), THEME_DARK)
    dark = QApplication.instance().palette().color(QPalette.Button)
    assert dark != light
    hh = w.table.horizontalHeader()
    vh = w.table.verticalHeader()
    assert hh.palette().color(QPalette.Button) == dark
    assert vh.palette().color(QPalette.Button) == dark
    apply_application_theme(QApplication.instance(), THEME_LIGHT)
    assert hh.palette().color(QPalette.Button) == light
    w.deleteLater()


def test_table_font_resizes_main_window_headers(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w._set_table_font_pt(8, persist=False)
    h_small = int(w.table.horizontalHeader().height())
    w_small = int(w.table.verticalHeader().width())
    w._set_table_font_pt(24, persist=False)
    assert int(w.table.horizontalHeader().height()) > h_small
    assert int(w.table.verticalHeader().width()) > w_small
    w._set_table_font_pt(8, persist=False)
    assert int(w.table.horizontalHeader().height()) == h_small
    w.deleteLater()


def test_ensure_fusion_style_is_idempotent(qapp):
    from molmanager.ui.theme import ensure_fusion_style

    ensure_fusion_style(qapp)
    assert qapp.style().objectName().lower() == "fusion"
    assert ensure_fusion_style(qapp) is False
    assert qapp.style().objectName().lower() == "fusion"


def test_apply_application_theme_preserves_app_font_pt(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from molmanager.ui.theme import apply_application_font_pt, apply_application_theme

    apply_application_font_pt(14)
    apply_application_theme(qapp, THEME_DARK)
    assert qapp.font().pointSize() == 14
    apply_application_theme(qapp, THEME_LIGHT)
    assert qapp.font().pointSize() == 14
    apply_application_font_pt(default_app_font_pt())


def test_gui_theme_switch_does_not_resize_fonts(qapp, tmp_path, monkeypatch):
    _isolate_theme_settings(tmp_path, monkeypatch)
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.theme import apply_application_font_pt

    w = ChemistryWorkspaceWindow()
    w._set_app_font_pt(14, persist=False)
    w._set_table_font_pt(14, persist=False)
    header_h = int(w.table.horizontalHeader().height())
    app_pt = int(qapp.font().pointSize())
    mb_pt = int(w.menuBar().font().pointSize())
    table_pt = int(w.table.font().pointSize())
    layout_btn = w._btn_workspace_layout
    layout_pt = int(layout_btn.font().pointSize()) if layout_btn is not None else mb_pt
    w._set_gui_theme(THEME_DARK)
    assert int(qapp.font().pointSize()) == app_pt
    assert int(w.menuBar().font().pointSize()) == mb_pt
    assert int(w.table.font().pointSize()) == table_pt
    assert int(w.table.horizontalHeader().height()) == header_h
    if layout_btn is not None:
        assert int(layout_btn.font().pointSize()) == layout_pt
        assert int(layout_btn.font().pointSize()) == int(w.menuBar().font().pointSize())
    w._set_gui_theme(THEME_LIGHT)
    assert int(w.table.font().pointSize()) == table_pt
    assert int(w.table.horizontalHeader().height()) == header_h
    apply_application_font_pt(default_app_font_pt())
    w.deleteLater()
