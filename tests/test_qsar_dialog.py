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

"""QSAR dialog layout: optional fingerprint, scope, and a window that fits the form."""

from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox, QScrollArea


def test_qsar_dialog_options_fit_without_a_scroll_area(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.qsar import QSARDialog

    dlg = QSARDialog(None)
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.findChildren(QScrollArea) == []
        assert dlg.train_btn.text() == "Train/Evaluate"
        assert dlg.fp_combo.itemText(0) == "None"
        assert dlg.fp_combo.currentIndex() == 0
        assert not dlg.struct_src_combo.isEnabled()
        assert not hasattr(dlg, "include_fp_cb")
        assert not hasattr(dlg, "chk_visible")
        assert not hasattr(dlg, "btn_refresh")
        assert not hasattr(dlg, "_btn_col_all")
        assert not hasattr(dlg, "_btn_col_none")
        parent = dlg.only_selected_cb.parent()
        assert isinstance(parent, QGroupBox)
        assert parent.title() == "Activity (Y)"

        svr = dlg.model_combo.findData("svr")
        assert svr >= 0
        dlg.model_combo.setCurrentIndex(svr)
        qapp.processEvents()
        host = dlg._options_host
        assert host.height() >= host.sizeHint().height() - 2
        assert host.height() <= dlg.contentsRect().height()
    finally:
        dlg.close()
