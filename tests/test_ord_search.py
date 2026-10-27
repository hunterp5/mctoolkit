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

"""Open Reaction Database query options."""

from __future__ import annotations

import pytest

from molmanager.sources.ord_search import OrdSearchOptions, OrdSearchResult, build_ord_query


def test_default_query_is_the_reaction_and_a_limit() -> None:
    query = build_ord_query(OrdSearchOptions("CO>>COC"))
    assert query["limit"] == 100
    assert query["where"] == {"op": "reaction_smarts", "smarts": "CO>>COC", "chirality": False}
    assert "order_by" not in query


def test_filters_become_clauses() -> None:
    query = build_ord_query(
        OrdSearchOptions(
            " CO>>COC ",
            chirality=True,
            limit=20,
            recorded_temperature=True,
            min_celsius=0,
            max_celsius=25,
            min_yield_percent=50,
            component_role="SOLVENT",
            component_structure="c1ccncc1",
            component_match="substructure",
            order="yield_desc",
        )
    )
    assert query["limit"] == 20
    clauses = query["where"]["clauses"]
    assert clauses[0]["chirality"] is True
    assert {"op": "not_null", "path": "conditions.temperature.setpoint_kelvin"} in clauses
    assert {
        "op": "ge",
        "path": "conditions.temperature.setpoint_kelvin",
        "value": {"literal": 273.15},
    } in clauses
    assert {
        "op": "le",
        "path": "conditions.temperature.setpoint_kelvin",
        "value": {"literal": 298.15},
    } in clauses
    yield_clause = next(
        item for item in clauses if item.get("path") == "outcomes.products.measurements"
    )
    assert yield_clause["where"]["clauses"][1]["value"]["literal"] == 50
    component = next(item for item in clauses if item.get("path") == "inputs.components")
    assert {"op": "eq", "path": "reaction_role", "value": {"literal": "SOLVENT"}} in component[
        "where"
    ]["clauses"]
    assert query["order_by"][0]["key"]["reduce"] == "max"
    assert query["order_by"][0]["descending"] is True


def test_same_parent_match_ignores_an_empty_role() -> None:
    query = build_ord_query(
        OrdSearchOptions(
            "CO>>COC",
            component_structure="CC(=O)[O-].[Na+]",
            component_match="same_parent",
        )
    )
    component = query["where"]["clauses"][1]
    assert component["where"] == {
        "op": "same_parent",
        "path": "smiles",
        "smiles": "CC(=O)[O-].[Na+]",
    }


def test_blank_reaction_is_refused() -> None:
    with pytest.raises(ValueError, match="reaction SMARTS"):
        build_ord_query(OrdSearchOptions("ethanol"))


def test_dialog_reads_the_form_and_lists_results(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices

    from molmanager.ui.dialogs import ord_search as ord_dialog
    from molmanager.ui.dialogs.ord_search import OrdSearchDialog

    dialog = OrdSearchDialog("CO>>COC")
    dialog.min_temperature.setText("0")
    dialog.recorded_temperature.setChecked(True)
    dialog.role.setCurrentIndex(dialog.role.findData("CATALYST"))
    dialog.structure.setText("c1ccncc1")
    dialog.match.setCurrentIndex(dialog.match.findData("similarity"))
    assert dialog.similarity.isEnabled()
    query = dialog.query()
    assert query["where"]["clauses"][0]["smarts"] == "CO>>COC"
    assert any(item.get("op") == "not_null" for item in query["where"]["clauses"])
    assert any(item.get("path") == "inputs.components" for item in query["where"]["clauses"])

    class _Pool:
        def start(self, runnable) -> None:
            runnable.run()

    dialog._pool = _Pool()
    dialog._search_fn = lambda _query: OrdSearchResult(["ord-abc"], True)
    opened: list[str] = []
    original = QDesktopServices.openUrl
    QDesktopServices.openUrl = lambda url: opened.append(url.toString()) or True  # type: ignore[method-assign]
    try:
        dialog.search_button.click()
        assert dialog.results.rowCount() == 1
        assert dialog.results.item(0, 0).text() == "ord-abc"
        assert "capped" in dialog.status.text()
        dialog.results.selectRow(0)
        dialog.open_button.click()
        assert opened == [ord_dialog.reaction_record_url("ord-abc")]
        assert QUrl(opened[0]).host() == "open-reaction-database.org"
    finally:
        QDesktopServices.openUrl = original  # type: ignore[method-assign]
        dialog.close()


def test_dialog_shows_a_search_error(qapp) -> None:  # noqa: ARG001
    from molmanager.sources.ord_search import OrdSearchError
    from molmanager.ui.dialogs.ord_search import OrdSearchDialog

    dialog = OrdSearchDialog("CO>>COC")

    class _Pool:
        def start(self, runnable) -> None:
            runnable.run()

    def _fail(_query):
        raise OrdSearchError("too broad")

    dialog._pool = _Pool()
    dialog._search_fn = _fail
    dialog.search_button.click()
    assert dialog.status.text() == "too broad"
    assert dialog.search_button.isEnabled()
    dialog.min_temperature.setText("hot")
    dialog.search_button.click()
    assert dialog.status.text() == "Minimum temperature must be a number."
    dialog.close()


def test_sketcher_button_writes_a_complete_reaction(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QApplication, QMessageBox

    import molmanager.ui.sketcher.dialog as sketch_dialog
    from molmanager.ui.dialogs.ord_search import OrdSearchDialog

    loaded: list[str] = []

    class _Canvas:
        def __init__(self, nodes: list[int], smarts: str) -> None:
            self.nodes = nodes
            self.reaction_arrow = (1, 2) if nodes else None
            self.smarts = smarts

        def load_reaction_smarts(self, text: str) -> bool:
            loaded.append(text)
            return True

        def to_reaction_smarts(self) -> str:
            return self.smarts

    class _Sketch:
        def __init__(
            self, parent=None, *, nodes: list[int] | None = None, smarts: str = ""
        ) -> None:
            self.canvas = _Canvas(list(nodes or []), smarts)

        def setModal(self, *_args) -> None:
            return None

        def setWindowModality(self, *_args) -> None:
            return None

        def setAttribute(self, *_args) -> None:
            return None

        def exec_(self) -> int:
            QApplication.processEvents()
            return 0

        def deleteLater(self) -> None:
            return None

        def show_sketch_status(self, _message: str) -> None:
            return None

    monkeypatch.setattr(
        sketch_dialog,
        "SketcherDialog",
        lambda parent=None: _Sketch(parent, nodes=[1], smarts="C>>CO"),
    )
    dialog = OrdSearchDialog("CC.O>>CCO")
    dialog.sketch_button.click()
    assert loaded == ["CC.O>>CCO"]
    assert dialog.reaction.toPlainText() == "C>>CO"

    notices: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: notices.append("shown"),
    )
    monkeypatch.setattr(
        sketch_dialog,
        "SketcherDialog",
        lambda parent=None: _Sketch(parent, nodes=[1], smarts=""),
    )
    dialog.sketch_button.click()
    assert dialog.reaction.toPlainText() == "C>>CO"
    assert notices == ["shown"]

    monkeypatch.setattr(
        sketch_dialog,
        "SketcherDialog",
        lambda parent=None: _Sketch(parent, nodes=[], smarts=""),
    )
    dialog.sketch_button.click()
    assert dialog.reaction.toPlainText() == "C>>CO"
    assert notices == ["shown"]
    dialog.close()
