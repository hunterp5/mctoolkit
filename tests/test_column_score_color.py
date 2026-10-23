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

"""Auto green–red coloring for QED, AB-MPS, BBB, and CNS MPO score columns."""

from __future__ import annotations

from PyQt5.QtCore import Qt

from molmanager.table.column_score_color import favorable_score_color_spec
from molmanager.ui.compound_table_model import CompoundTableModel


def test_score_header_matching() -> None:
    assert favorable_score_color_spec("QED Score") is not None
    assert favorable_score_color_spec("QED Score (1)") is not None
    assert favorable_score_color_spec("AB-MPS score") is not None
    assert favorable_score_color_spec("AB-MPS score (2)") is not None
    assert favorable_score_color_spec("CNS MPO score") is not None
    assert favorable_score_color_spec("BBB Score") is not None
    assert favorable_score_color_spec("BBB Score (2)") is not None
    assert favorable_score_color_spec("CNS-MPO score") is not None
    assert favorable_score_color_spec("QED") is None
    assert favorable_score_color_spec("MolWt") is None
    qed = favorable_score_color_spec("QED Score")
    ab = favorable_score_color_spec("AB-MPS score")
    cns = favorable_score_color_spec("CNS MPO score")
    bbb = favorable_score_color_spec("BBB Score")
    assert qed is not None and qed.higher_is_better
    assert ab is not None and not ab.higher_is_better
    assert cns is not None and cns.higher_is_better
    assert bbb is not None and bbb.higher_is_better
    assert bbb.mid_value == 4.0


def test_qed_and_cns_mpo_high_values_are_greener(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "QED Score", "CNS MPO score"])
    model.append_row(1, {"QED Score": "0.1", "CNS MPO score": "1.0"})
    model.append_row(2, {"QED Score": "0.9", "CNS MPO score": "5.5"})
    assert model.apply_favorable_score_column_coloring("QED Score")
    assert model.apply_favorable_score_column_coloring("CNS MPO score")
    qed_col = model._headers.index("QED Score")
    cns_col = model._headers.index("CNS MPO score")
    qed_low = model.data(model.index(0, qed_col), Qt.BackgroundRole)
    qed_high = model.data(model.index(1, qed_col), Qt.BackgroundRole)
    cns_low = model.data(model.index(0, cns_col), Qt.BackgroundRole)
    cns_high = model.data(model.index(1, cns_col), Qt.BackgroundRole)
    assert qed_high.green() > qed_low.green()
    assert qed_low.red() > qed_high.red()
    assert cns_high.green() > cns_low.green()
    assert cns_low.red() > cns_high.red()


def test_bbb_high_values_are_greener(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "BBB Score"])
    model.append_row(1, {"BBB Score": "1.5"})
    model.append_row(2, {"BBB Score": "5.5"})
    assert model.apply_favorable_score_column_coloring("BBB Score")
    col = model._headers.index("BBB Score")
    low = model.data(model.index(0, col), Qt.BackgroundRole)
    high = model.data(model.index(1, col), Qt.BackgroundRole)
    assert high.green() > low.green()
    assert low.red() > high.red()


def test_ab_mps_low_values_are_greener(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "AB-MPS score"])
    model.append_row(1, {"AB-MPS score": "2"})
    model.append_row(2, {"AB-MPS score": "22"})
    assert model.apply_favorable_score_column_coloring("AB-MPS score")
    col = model._headers.index("AB-MPS score")
    better = model.data(model.index(0, col), Qt.BackgroundRole)
    worse = model.data(model.index(1, col), Qt.BackgroundRole)
    assert better.green() > worse.green()
    assert worse.red() > better.red()


def test_non_score_column_is_not_auto_colored(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "MolWt"])
    model.append_row(1, {"MolWt": "180"})
    assert model.apply_favorable_score_column_coloring("MolWt") is False
    assert model.column_color_mode("MolWt") == ""
