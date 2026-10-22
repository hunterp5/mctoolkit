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

"""Tests for Data → Binning."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rdkit import Chem

from molmanager.plotting.plot_axes import compute_histogram_bin_edges
from molmanager.table.column_binning import (
    BinningParams,
    bin_column_texts,
    classification_labels,
    parse_custom_labels_text,
    parse_edges_text,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.strings import TOOL_BINNING


def _params(**kwargs) -> BinningParams:
    base = dict(
        source_column="LogP",
        range_column="LogP_bin",
        class_column="LogP_class",
        method="equal_width",
        bin_count=2,
    )
    base.update(kwargs)
    return BinningParams(**base)


def test_equal_width_writes_range_and_class() -> None:
    binned = bin_column_texts(["0", "2", "3", "6", "n/a"], _params())
    assert binned.range_names == ("[0, 3)", "[3, 6]")
    assert binned.ranges == ("[0, 3)", "[0, 3)", "[3, 6]", "[3, 6]", "")
    assert binned.classes == ("Inactive", "Inactive", "Active", "Active", "")
    assert binned.numeric_count == 4


def test_equal_width_constant_column_is_one_bin() -> None:
    binned = bin_column_texts(["3", "3", "3"], _params(bin_count=4))
    assert binned.range_names == ("3",)
    assert binned.ranges == ("3", "3", "3")
    assert binned.classes == ("Class 1", "Class 1", "Class 1")


def test_equal_width_respects_min_max() -> None:
    binned = bin_column_texts(
        ["0", "5", "10"],
        _params(bin_count=2, minimum=2, maximum=8),
    )
    assert binned.range_names == ("[2, 5)", "[5, 8]")
    assert binned.ranges == ("", "[5, 8]", "")
    assert binned.classes == ("", "Active", "")


def test_bin_width_aligns_with_histogram_edges() -> None:
    hist_edges, _width = compute_histogram_bin_edges([1, 9], bin_width=5)
    assert hist_edges == [0, 5, 10]
    binned = bin_column_texts(["1", "9"], _params(bin_width=5, bin_count=99))
    assert binned.ranges == ("[0, 5)", "[5, 10]")


def test_bin_width_stays_inside_explicit_range() -> None:
    binned = bin_column_texts(
        ["1", "9"],
        _params(bin_width=4, minimum=0, maximum=10),
    )
    assert binned.range_names == ("[0, 4)", "[4, 8)", "[8, 10]")
    assert binned.ranges == ("[0, 4)", "[8, 10]")


def test_equal_count_balances_and_keeps_ties_together() -> None:
    balanced = bin_column_texts(["1", "2", "3", "4"], _params(method="equal_count"))
    assert balanced.ranges == ("[1, 3)", "[1, 3)", "[3, 4]", "[3, 4]")
    tied = bin_column_texts(["1", "1", "1", "1", "5"], _params(method="equal_count"))
    assert tied.range_names == ("[1, 5)", "5")
    assert tied.ranges == ("[1, 5)", "[1, 5)", "[1, 5)", "[1, 5)", "5")


def test_custom_edges_open_and_closed() -> None:
    params = _params(method="custom", edges=(5.0, 7.0), open_ends=True)
    opened = bin_column_texts(["4", "5", "6", "7", "8"], params)
    assert opened.range_names == ("< 5", "[5, 7)", "≥ 7")
    assert opened.ranges == ("< 5", "[5, 7)", "[5, 7)", "≥ 7", "≥ 7")
    assert opened.classes == ("Low", "Medium", "Medium", "High", "High")
    closed = bin_column_texts(
        ["4", "5", "7", "8"],
        _params(method="custom", edges=(5.0, 7.0), open_ends=False),
    )
    assert closed.ranges == ("", "[5, 7]", "[5, 7]", "")
    assert closed.classes == ("", "Class 1", "Class 1", "")


def test_classification_labels_follow_bin_order() -> None:
    assert classification_labels(2) == ("Inactive", "Active")
    assert classification_labels(3) == ("Low", "Medium", "High")
    assert classification_labels(4) == ("Low", "Medium", "High", "Very high")
    assert classification_labels(5) == ("Class 1", "Class 2", "Class 3", "Class 4", "Class 5")
    two = bin_column_texts(["0", "6"], _params())
    assert two.ranges == ("[0, 3)", "[3, 6]")
    assert two.classes == ("Inactive", "Active")
    three = bin_column_texts(["0", "5", "10"], _params(bin_count=3))
    assert three.classes == ("Low", "Medium", "High")
    renamed = bin_column_texts(["0", "6"], _params(class_labels=("no", "yes")))
    assert renamed.classes == ("no", "yes")
    assert renamed.ranges == ("[0, 3)", "[3, 6]")
    with pytest.raises(ValueError, match="class labels"):
        bin_column_texts(["0", "6"], _params(class_labels=("only",)))


def test_edges_and_width_validation() -> None:
    assert parse_edges_text("5, 6; 7") == (5.0, 6.0, 7.0)
    assert parse_custom_labels_text(" low ; high ") == ("low", "high")
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_edges_text("1, 1, 2")
    with pytest.raises(ValueError, match="wider bin"):
        bin_column_texts(["0", "1000"], _params(bin_width=0.001))
    with pytest.raises(ValueError, match="No numeric values"):
        bin_column_texts(["", "abc", "nan"], _params())
    with pytest.raises(ValueError, match="No values fell into a bin"):
        bin_column_texts(["1", "2"], _params(method="custom", edges=(10.0, 12.0), open_ends=False))


def test_binning_writes_column(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "LogP"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "LogP": "0"})
    w._table_model.append_row(1, {"SMILES": "CCN", "LogP": "6"})
    w._table_model.append_row(2, {"SMILES": "CCC", "LogP": "n/a"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCN")
    w.mols[2] = Chem.MolFromSmiles("CCC")
    w.next_oid = 3

    accepted = SimpleNamespace(
        params=lambda: _params(),
        only_selected_rows=lambda: False,
    )
    w._on_binning_dialog_accepted(accepted)
    assert "LogP_bin" in w.headers
    assert "LogP_class" in w.headers
    col = w.headers.index("LogP_bin")
    klass = w.headers.index("LogP_class")
    assert w._table_model.cell_text(0, col) == "[0, 3)"
    assert w._table_model.cell_text(1, col) == "[3, 6]"
    assert w._table_model.cell_text(2, col) == ""
    assert w._table_model.cell_text(0, klass) == "Inactive"
    assert w._table_model.cell_text(1, klass) == "Active"
    assert w._table_model.cell_text(2, klass) == ""
    assert TOOL_BINNING in (w.status_label.text() or "")
    w.close()


def test_binning_selected_rows_only(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "LogP"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "LogP": "0"})
    w._table_model.append_row(1, {"SMILES": "CCN", "LogP": "6"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCN")
    w.next_oid = 2
    w.selection_store.set({0})

    accepted = SimpleNamespace(
        params=lambda: _params(),
        only_selected_rows=lambda: True,
    )
    w._on_binning_dialog_accepted(accepted)
    col = w.headers.index("LogP_bin")
    klass = w.headers.index("LogP_class")
    assert w._table_model.cell_text(0, col) == "0"
    assert w._table_model.cell_text(0, klass) == "Class 1"
    assert w._table_model.cell_text(1, col) == ""
    assert w._table_model.cell_text(1, klass) == ""
    w.close()


def test_binning_dialog_methods_and_params(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.binning import BinningDialog

    dlg = BinningDialog(["SMILES", "LogP"], 0)
    assert not hasattr(dlg, "preview_label")
    assert dlg.method_combo.currentData() == "equal_width"
    assert dlg.bin_count_spin.isHidden() is False
    assert dlg.edges_input.isHidden() is True
    assert dlg.open_ends_cb.isHidden() is True
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("custom"))
    assert dlg.edges_input.isHidden() is False
    assert dlg.bin_count_spin.isHidden() is True
    assert dlg.open_ends_cb.isHidden() is False
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("equal_width"))
    dlg.bin_count_spin.setValue(2)
    assert dlg.class_labels_input.isHidden() is False
    assert dlg.class_labels_input.text() == "Inactive; Active"
    dlg.col_combo.setCurrentText("LogP")
    assert dlg.params().range_column == "LogP_bin"
    assert dlg.params().class_column == "LogP_class"
    assert dlg.params().class_labels == ("Inactive", "Active")
    dlg.bin_count_spin.setValue(3)
    assert dlg.class_labels_input.text() == "Low; Medium; High"
    dlg.class_labels_input.setText("no; yes")
    dlg.bin_count_spin.setValue(4)
    assert dlg.class_labels_input.text() == "no; yes"
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("custom"))
    dlg.edges_input.setText("1, 2, 3")
    dlg.range_input.setText("Band")
    dlg.class_input.setText("BandClass")
    dlg.class_labels_input.setText("a; b; c; d")
    params = dlg.params()
    assert params.method == "custom"
    assert params.edges == (1.0, 2.0, 3.0)
    assert params.open_ends is True
    assert params.range_column == "Band"
    assert params.class_column == "BandClass"
    assert params.class_labels == ("a", "b", "c", "d")
    dlg.close()


def test_binning_help_topic() -> None:
    from molmanager.ui.user_guides import guide_html

    html = guide_html("data_binning")
    assert "Topic unavailable" not in html
    assert "Open ends" in html
    assert "Inactive" in html
