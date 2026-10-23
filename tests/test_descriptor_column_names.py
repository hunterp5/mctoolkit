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

"""Unique column names for descriptor calculation."""

from __future__ import annotations

from molmanager.ui.main_window.column_write_mixin import ColumnWriteMixin, cell_looks_uncalculated


class _Host(ColumnWriteMixin):
    def __init__(self, headers: list[str]) -> None:
        self.headers = list(headers)


class _ModelHost(ColumnWriteMixin):
    def __init__(self, headers: list[str], rows: dict[int, dict[str, str]]) -> None:
        self.headers = list(headers)
        self._rows = rows

        class _Model:
            def __init__(self, outer: _ModelHost) -> None:
                self._outer = outer

            def logical_row_for_oid(self, oid: int) -> int:
                return oid if oid in self._outer._rows else -1

            def backing_value_for_row_header(self, row: int, header: str) -> str:
                return str(self._outer._rows.get(row, {}).get(header, "") or "")

        self._table_model = _Model(self)


def test_unique_table_column_names_skips_existing() -> None:
    host = _Host(["ID_HIDDEN", "Structure", "LogP", "LogP (1)"])
    names = host._unique_table_column_names(["LogP", "TPSA"])
    assert names == ["LogP (2)", "TPSA"]


def test_unique_table_column_names_dedupes_batch() -> None:
    host = _Host(["ID_HIDDEN", "Structure"])
    names = host._unique_table_column_names(["Score", "Score", "Other"])
    assert names == ["Score", "Score (1)", "Other"]


def test_cell_looks_uncalculated_covers_placeholders() -> None:
    assert cell_looks_uncalculated("")
    assert cell_looks_uncalculated("N/A")
    assert cell_looks_uncalculated("Cancelled.")
    assert cell_looks_uncalculated("Error (see log)")
    assert not cell_looks_uncalculated("1.23")


def test_result_column_names_reuses_when_selected_cells_are_empty() -> None:
    host = _ModelHost(
        ["ID_HIDDEN", "Structure", "SOM Map", "LogP"],
        {0: {"SOM Map": "CCO", "LogP": "1.2"}, 1: {"SOM Map": "", "LogP": ""}},
    )
    names = host._result_column_names(["SOM Map", "LogP"], [1])
    assert names == ["SOM Map", "LogP"]


def test_result_column_names_reuses_cancelled_placeholder() -> None:
    host = _ModelHost(
        ["ID_HIDDEN", "Structure", "SOM Map"],
        {0: {"SOM Map": "CCO"}, 1: {"SOM Map": "Cancelled."}},
    )
    names = host._result_column_names(["SOM Map"], [1])
    assert names == ["SOM Map"]


def test_result_column_names_reuses_error_placeholder() -> None:
    host = _ModelHost(
        ["ID_HIDDEN", "Structure", "pKa"],
        {0: {"pKa": "Error (see log)"}},
    )
    # pKa always reuses; also cover a non-always column with error text
    host2 = _ModelHost(
        ["ID_HIDDEN", "Structure", "LogP"],
        {0: {"LogP": "Error (see log)"}},
    )
    assert host._result_column_names(["pKa"], [0]) == ["pKa"]
    assert host2._result_column_names(["LogP"], [0]) == ["LogP"]


def test_result_column_names_suffixes_when_all_selected_cells_are_filled() -> None:
    host = _ModelHost(
        ["ID_HIDDEN", "Structure", "LogP"],
        {0: {"LogP": "1.23"}},
    )
    names = host._result_column_names(["LogP"], [0])
    assert names == ["LogP (1)"]


def test_on_calc_finished_does_not_replace_existing_column(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "LogP"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"LogP": "1.23"})
    w.mols = {}
    w.next_oid = 1

    written = w.on_calc_finished(
        [(0, {"LogP": "9.99"})],
        ["LogP"],
        finish_progress=False,
    )
    assert written == ["LogP (1)"]
    assert "LogP" in w.headers
    assert "LogP (1)" in w.headers
    assert w._table_model.value_for_header(0, "LogP") == "1.23"
    assert w._table_model.value_for_header(0, "LogP (1)") == "9.99"
    w.close()


def test_on_calc_finished_colors_qed_score(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {})
    w.mols = {}
    w.next_oid = 1
    written = w.on_calc_finished(
        [(0, {"QED Score": "0.80"})],
        ["QED Score"],
        finish_progress=False,
    )
    assert written == ["QED Score"]
    spec = w._table_model.column_color_rule_spec("QED Score")
    assert spec is not None
    assert spec["mode"] == "numeric3"
    w.close()


def test_on_calc_finished_updates_pka_and_pi_in_place(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "pKa", "pI"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"pKa": "4.76", "pI": "N/A"})
    w.mols = {}
    w.next_oid = 1

    written = w.on_calc_finished(
        [(0, {"pKa": "9.50", "pI": "5.97"})],
        ["pKa", "pI"],
        finish_progress=False,
    )
    assert written == ["pKa", "pI"]
    assert w.headers.count("pKa") == 1
    assert "pKa (1)" not in w.headers
    assert w._table_model.value_for_header(0, "pKa") == "9.50"
    assert w._table_model.value_for_header(0, "pI") == "5.97"
    w.close()


def test_on_calc_finished_reuses_column_for_empty_rows(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    score = "Score"
    detail = "Detail"
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", score, detail]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {score: "CCO", detail: "0"})
    w._table_model.append_row(1, {})
    w.mols = {}
    w.next_oid = 2
    written = w.on_calc_finished(
        [(1, {score: "c1ccccc1", detail: "1"})],
        [score, detail],
        finish_progress=False,
    )
    assert written == [score, detail]
    assert f"{score} (1)" not in w.headers
    assert w._table_model.value_for_header(0, score) == "CCO"
    assert w._table_model.value_for_header(1, score) == "c1ccccc1"
    w.close()


def test_on_calc_finished_chunks_large_write(qapp, monkeypatch):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_rows_batch([(i, {}) for i in range(4)])
    w.mols = {}
    w.next_oid = 4
    monkeypatch.setattr(w, "_calc_writeback_async_min_rows", lambda: 2)
    monkeypatch.setattr(w, "_calc_writeback_chunk_rows", lambda: 2)
    completed: list[list[str]] = []
    written = w.on_calc_finished(
        [(i, {"LogP": str(i)}) for i in range(4)],
        ["LogP"],
        finish_progress=False,
        on_complete=completed.append,
    )
    assert written == ["LogP"]
    for _ in range(40):
        qapp.processEvents()
        if completed:
            break
    assert completed == [["LogP"]]
    assert [w._table_model.value_for_header(i, "LogP") for i in range(4)] == [
        "0",
        "1",
        "2",
        "3",
    ]
    w.close()
