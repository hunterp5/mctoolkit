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

"""Shared look-and-feel for result browsers (preview wells, tables, floating shell)."""

from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ...table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ..dockable_plot import PLOT_BODY_MARGINS, PLOT_BODY_SPACING
from ..dockable_plot_constants import _BROWSER_NAV_BTN_HEIGHT
from ..qt_widget_utils import make_window_minimizable

# RDKit depictions sit on white; keep the well white in light and dark app themes.
BROWSER_PREVIEW_CANVAS_QSS = (
    "background-color: #ffffff; border: 1px solid palette(mid); border-radius: 4px;"
)
BROWSER_PREVIEW_FRAME_QSS = "border: 1px solid palette(mid); border-radius: 4px;"
BROWSER_PREVIEW_STRUCT_QSS = "background-color: #ffffff; border: none; padding: 0px;"
BROWSER_DATA_TABLE_QSS = (
    "QTableWidget { background-color: palette(base); "
    "border: 1px solid palette(mid); border-radius: 4px; }"
)
BROWSER_GROUP_QSS = (
    "QGroupBox { margin-top: 10px; background-color: palette(base); "
    "border: 1px solid palette(mid); border-radius: 4px; }"
)
BROWSER_EMPHASIS_LABEL_QSS = "font-weight: 600;"

BROWSER_FLOATING_MIN_WIDTH = 480
BROWSER_FLOATING_MIN_HEIGHT = 520
BROWSER_CLOSE_TITLE = "Close Browser"
BROWSER_CLOSE_MESSAGE = "Close this browser?"


def apply_browser_body_layout(layout: QVBoxLayout) -> None:
    """Match docked-plot body padding so floating and docked browsers sit the same."""
    layout.setContentsMargins(*PLOT_BODY_MARGINS)
    layout.setSpacing(PLOT_BODY_SPACING)


def style_browser_preview_host(widget: QWidget, *, canvas: bool = True) -> None:
    """Frame the structure preview: white canvas for 2D, border-only for 3D."""
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setStyleSheet(BROWSER_PREVIEW_CANVAS_QSS if canvas else BROWSER_PREVIEW_FRAME_QSS)


def style_browser_structure_label(label: QLabel) -> None:
    """White, borderless RDKit depiction surface inside a preview well."""
    label.setAlignment(Qt.AlignCenter)
    label.setScaledContents(False)
    label.setStyleSheet(BROWSER_PREVIEW_STRUCT_QSS)


def style_browser_data_table(table: QTableWidget) -> None:
    """Rounded well used by pose/selection row tables and SOM/metabolite lists."""
    table.setStyleSheet(BROWSER_DATA_TABLE_QSS)


def style_browser_group_box(box: QGroupBox) -> None:
    """Property / molecule grouping used by pair browsers."""
    box.setStyleSheet(BROWSER_GROUP_QSS)


def style_browser_emphasis_label(label: QLabel) -> None:
    label.setStyleSheet(BROWSER_EMPHASIS_LABEL_QSS)


def make_browser_preview_host(
    parent: QWidget | None,
    *,
    canvas: bool = True,
) -> tuple[QWidget, QVBoxLayout]:
    """Preview well with a zero-margin inner layout."""
    host = QWidget(parent)
    style_browser_preview_host(host, canvas=canvas)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    return host, layout


def make_pair_mol_panel(title: str, parent: QWidget | None = None) -> dict[str, Any]:
    """Side-by-side molecule card: titled group, white structure well, activity caption."""
    box = QGroupBox(title, parent)
    style_browser_group_box(box)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)
    struct = QLabel(box)
    style_browser_structure_label(struct)
    struct.setMinimumSize(
        BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2,
        BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2,
    )
    struct.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    struct.setAttribute(Qt.WA_StyledBackground, True)
    activity = QLabel("—", box)
    activity.setAlignment(Qt.AlignCenter)
    activity.setTextInteractionFlags(Qt.TextSelectableByMouse)
    activity.setWordWrap(True)
    layout.addWidget(struct, 1)
    layout.addWidget(activity)
    return {"box": box, "struct": struct, "activity": activity}


def make_pair_prop_value_row() -> dict[str, Any]:
    """A | B property values for the three shared pair-browser pickers."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    lab_a = QLabel("—")
    lab_b = QLabel("—")
    for lab in (lab_a, lab_b):
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setWordWrap(True)
        lab.setMinimumWidth(120)
    row.addWidget(lab_a, 1)
    row.addWidget(lab_b, 1)
    field = QWidget()
    field.setLayout(row)
    return {"host": field, "a": lab_a, "b": lab_b}


def make_pair_prop_box(parent: QWidget | None = None) -> tuple[QGroupBox, QFormLayout]:
    """Three column-picker rows comparing molecule A and B."""
    box = QGroupBox(parent)
    style_browser_group_box(box)
    form = QFormLayout(box)
    form.setLabelAlignment(Qt.AlignRight)
    form.setFormAlignment(Qt.AlignTop)
    form.setContentsMargins(12, 12, 12, 10)
    form.setVerticalSpacing(8)
    form.setHorizontalSpacing(10)
    return box, form


def configure_browser_mol_drawer(drawer: Any, width: int) -> None:
    """Apply the shared RDKit drawer theme when the helper is available."""
    try:
        from ...chem.structure_2d_depiction import configure_mol_drawer as cfg

        cfg(drawer, width)
    except Exception:
        pass


class BrowserIndexSpinBox(QSpinBox):
    """Index field. Focus selects the current value so typing replaces it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setRange(1, 1)
        self.setAlignment(Qt.AlignCenter)
        self.setButtonSymbols(QSpinBox.NoButtons)
        self.setKeyboardTracking(False)
        self.setFixedWidth(72)
        self.setFixedHeight(_BROWSER_NAV_BTN_HEIGHT)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("Type a number and press Enter to jump.")

    def focusInEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().focusInEvent(event)
        edit = self.lineEdit()
        if edit is not None:
            edit.selectAll()


def install_browser_nav_shortcuts(
    widget: QWidget,
    *,
    go_first: Callable[[], None],
    step: Callable[[int], None],
    go_last: Callable[[], None],
) -> None:
    """Home / ← / → / End while focus is anywhere in the browser."""
    for key, slot in (
        (Qt.Key_Home, go_first),
        (Qt.Key_Left, lambda: step(-1)),
        (Qt.Key_Right, lambda: step(1)),
        (Qt.Key_End, go_last),
    ):
        sc = QShortcut(QKeySequence(key), widget)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(slot)


def floating_browser_minimum_width(panel: QWidget, *, floor: int = 360) -> int:
    """Width needed for footer + nav chrome without clipping."""
    margins = 8
    widths = [floor]
    embedded = getattr(panel, "embedded_minimum_width", None)
    if callable(embedded):
        try:
            widths.append(int(embedded()))
        except Exception:
            pass
    for bar in (getattr(panel, "_footer_bar", None), getattr(panel, "_nav_bar", None)):
        if bar is None:
            continue
        try:
            hint = bar.sizeHint()
            min_hint = bar.minimumSizeHint()
            widths.append(max(int(hint.width()), int(min_hint.width()), 0))
        except RuntimeError:
            continue
    return max(widths) + margins


class BrowserHostDialog(QDialog):
    """Floating shell that hosts a dockable browser panel."""

    close_title = BROWSER_CLOSE_TITLE
    close_message = BROWSER_CLOSE_MESSAGE
    default_title = "Browser"
    panel_cls: type[QWidget] | None = None
    fit_chrome = False
    sync_options_chrome = False
    refresh_preview_on_show = False
    min_size: tuple[int, int] | None = None
    initial_size: tuple[int, int] | None = None

    def __init__(self, parent: Any = None, *, panel: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(self.default_title)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self._force_close = False

        if panel is not None:
            self._panel = panel
            self._panel.setParent(self)
            rebind = getattr(self._panel, "rebind_parent_app", None)
            if callable(rebind):
                rebind(parent)
            self._panel.show()
        else:
            self._panel = self._create_panel(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        if self.fit_chrome:
            root.setSizeConstraint(QLayout.SetDefaultConstraint)
        root.addWidget(self._panel, 1)
        sync_footer = getattr(self._panel, "_sync_footer_chrome", None)
        if callable(sync_footer):
            sync_footer()
        if self.sync_options_chrome:
            sync_opts = getattr(self._panel, "_sync_options_chrome", None)
            if callable(sync_opts):
                sync_opts()
        make_window_minimizable(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        if self.min_size is not None:
            self.setMinimumSize(*self.min_size)
        if self.initial_size is not None:
            self.resize(*self.initial_size)
        if self.fit_chrome:
            self.ensure_fits_chrome(initial=True)

    def _create_panel(self, parent_app: Any) -> QWidget:
        cls = self.panel_cls
        if cls is None:
            raise TypeError(f"{type(self).__name__} must set panel_cls or pass panel=")
        return cls(parent_app, self)

    def ensure_fits_chrome(self, *, initial: bool = False) -> None:
        """Keep the floating window at least as wide as footer/nav chrome."""
        panel = getattr(self, "_panel", None)
        if panel is None:
            return
        try:
            min_w = int(panel.floating_content_minimum_width())
        except Exception:
            min_w = BROWSER_FLOATING_MIN_WIDTH
        min_w = max(BROWSER_FLOATING_MIN_WIDTH, min_w)
        self.setMinimumWidth(min_w)
        if initial:
            height = max(
                BROWSER_FLOATING_MIN_HEIGHT,
                int(self.height()) or BROWSER_FLOATING_MIN_HEIGHT,
            )
            self.resize(min_w, height)
        elif self.width() < min_w:
            self.resize(min_w, self.height())

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt API
        hint = super().sizeHint()
        if not self.fit_chrome:
            return hint
        panel = getattr(self, "_panel", None)
        if panel is None:
            return hint
        try:
            min_w = int(panel.floating_content_minimum_width())
        except Exception:
            min_w = hint.width()
        return QSize(
            max(hint.width(), min_w, BROWSER_FLOATING_MIN_WIDTH),
            max(hint.height(), BROWSER_FLOATING_MIN_HEIGHT),
        )

    def showEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().showEvent(event)
        if self.refresh_preview_on_show:
            QTimer.singleShot(0, self._refresh_panel_preview)

    def _refresh_panel_preview(self) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        panel = getattr(self, "_panel", None)
        if panel is None or qobject_is_deleted(panel):
            return
        refresh = getattr(panel, "_refresh_preview", None)
        if callable(refresh):
            refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        from ..dockable_plot import handle_floating_plot_close_event

        if getattr(self, "_panel", None) is not None and self._panel.parent() is not self:
            self._force_close = True
            self._panel = None
        handle_floating_plot_close_event(
            self,
            event,
            title=self.close_title,
            message=self.close_message,
        )
        if event.isAccepted():
            self._on_close_accepted()

    def _on_close_accepted(self) -> None:
        """Subclass hook after the floating window is closed or hidden."""
        return
