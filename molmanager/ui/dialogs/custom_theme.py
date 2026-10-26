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

"""Named custom GUI theme editor (Settings → GUI → Theme → Custom Colors)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import make_window_minimizable
from ..theme import (
    CUSTOM_PALETTE_ROLES,
    current_theme_name,
    custom_theme_display_name,
    default_custom_palette_colors,
    delete_custom_theme,
    is_custom_theme_id,
    list_custom_theme_names,
    load_custom_theme_colors,
    save_custom_theme,
)

_NEW_THEME_LABEL = "(New theme)"


class CustomThemeDialog(QDialog):
    """Create, switch, save, and delete named custom GUI themes."""

    def __init__(self, parent=None, *, initial_colors: dict[str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Custom Colors")
        self.setMinimumWidth(300)
        self.resize(340, 0)
        make_window_minimizable(self)

        self._colors = dict(default_custom_palette_colors())
        self._buttons: dict[str, QPushButton] = {}
        self._saved_name: str | None = None
        self._deleted_name: str | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._theme_row_widget = QWidget()
        theme_row = QHBoxLayout(self._theme_row_widget)
        theme_row.setContentsMargins(0, 0, 0, 0)
        theme_row.addWidget(QLabel("Theme:"))
        self._theme_combo = QComboBox()
        self._theme_combo.setMinimumWidth(140)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        theme_row.addWidget(self._theme_combo, 1)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setToolTip("Delete the selected saved theme.")
        self._delete_btn.clicked.connect(self._delete_current)
        theme_row.addWidget(self._delete_btn)
        root.addWidget(self._theme_row_widget)

        form = QFormLayout()
        form.setSpacing(4)
        form.setContentsMargins(0, 4, 0, 4)
        form.setFormAlignment(Qt.AlignHCenter | Qt.AlignTop)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        for key, label, _role in CUSTOM_PALETTE_ROLES:
            swatch = QPushButton()
            swatch.setFixedSize(64, 22)
            swatch.setToolTip(f"Pick color for {label}")
            swatch.clicked.connect(lambda *_a, k=key: self._pick(k))
            self._buttons[key] = swatch
            form.addRow(f"{label}:", swatch)
        form_wrap = QHBoxLayout()
        form_wrap.addStretch(1)
        form_wrap.addLayout(form)
        form_wrap.addStretch(1)
        root.addLayout(form_wrap)

        actions = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Theme name")
        actions.addWidget(self._name_edit, 1)
        self._save_btn = QPushButton("Save")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save_current)
        actions.addWidget(self._save_btn)
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setToolTip("Reset to light mode defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        actions.addWidget(reset_btn)
        root.addLayout(actions)

        start_name = ""
        cur = current_theme_name()
        if is_custom_theme_id(cur):
            start_name = custom_theme_display_name(cur)
        self._rebuild_theme_combo(select_name=start_name or None)

        if initial_colors:
            for k, v in initial_colors.items():
                c = QColor(str(v))
                if c.isValid():
                    self._colors[k] = c.name()
            self._refresh_buttons()

    def saved_theme_name(self) -> str | None:
        """Display name of the theme saved in this session, if any."""
        return self._saved_name

    def deleted_theme_name(self) -> str | None:
        """Display name of a theme deleted in this session, if any."""
        return self._deleted_name

    def selected_colors(self) -> dict[str, str]:
        return {k: str(v) for k, v in self._colors.items()}

    def _update_theme_switcher_visibility(self, names: list[str]) -> None:
        # Only show switch/delete once the user has at least one saved theme.
        self._theme_row_widget.setVisible(bool(names))

    def _rebuild_theme_combo(self, *, select_name: str | None = None) -> None:
        self._loading = True
        self._theme_combo.blockSignals(True)
        self._theme_combo.clear()
        self._theme_combo.addItem(_NEW_THEME_LABEL, "")
        names = list_custom_theme_names()
        for name in names:
            self._theme_combo.addItem(name, name)
        self._update_theme_switcher_visibility(names)
        idx = 0
        if select_name and select_name in names:
            idx = names.index(select_name) + 1
        self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.blockSignals(False)
        self._loading = False
        self._on_theme_selected(idx)

    def _on_theme_selected(self, _index: int = 0) -> None:
        if self._loading:
            return
        name = str(self._theme_combo.currentData() or "")
        if name:
            self._colors = load_custom_theme_colors(name)
            self._name_edit.setText(name)
            self._delete_btn.setEnabled(True)
        else:
            self._colors = default_custom_palette_colors()
            self._name_edit.clear()
            self._delete_btn.setEnabled(False)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        for key, btn in self._buttons.items():
            c = QColor(self._colors.get(key, "#888888"))
            btn.setStyleSheet(
                f"background-color: {c.name()}; border: 1px solid #666; border-radius: 3px;"
            )
            btn.setText(c.name())

    def _pick(self, key: str) -> None:
        start = QColor(self._colors.get(key, "#888888"))
        chosen = QColorDialog.getColor(start, self, f"Pick {key.replace('_', ' ')}")
        if not chosen.isValid():
            return
        self._colors[key] = chosen.name()
        self._refresh_buttons()

    def _reset_defaults(self) -> None:
        self._colors = default_custom_palette_colors()
        self._refresh_buttons()

    def _save_current(self) -> None:
        name = " ".join(self._name_edit.text().split()).strip()
        if not name:
            QMessageBox.warning(self, "Save theme", "Enter a name for this color scheme.")
            self._name_edit.setFocus()
            return
        saved = save_custom_theme(name, self._colors)
        self._saved_name = saved
        self._name_edit.setText(saved)
        self.accept()

    def _delete_current(self) -> None:
        name = str(self._theme_combo.currentData() or "")
        if not name:
            return
        reply = QMessageBox.question(
            self,
            "Delete theme",
            f'Delete the custom theme "{name}"?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if not delete_custom_theme(name):
            return
        self._deleted_name = name
        if self._saved_name == name:
            self._saved_name = None
        next_names = list_custom_theme_names()
        self._rebuild_theme_combo(select_name=next_names[0] if next_names else None)
