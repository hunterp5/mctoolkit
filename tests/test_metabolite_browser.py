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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Tests for the Predict Metabolites results browser."""

from __future__ import annotations

from molmanager.table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from molmanager.ui.dockable_plot import is_dockable_workspace_widget
from molmanager.ui.metabolite_browser import (
    ROLE_METABOLITE,
    ROLE_PARENT,
    MetaboliteBrowseHit,
    MetaboliteBrowseRecord,
    MetaboliteBrowserDialog,
    MetaboliteBrowserWidget,
)


def test_metabolite_browser_widget_is_workspace_dockable():
    assert getattr(MetaboliteBrowserWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(MetaboliteBrowserWidget)
    assert hasattr(MetaboliteBrowserWidget, "create_floating_dialog")


def test_metabolite_browser_includes_parent_row(qapp) -> None:  # noqa: ARG001
    recs = [
        MetaboliteBrowseRecord(
            oid=1,
            smiles="CCO",
            metabolites=(
                MetaboliteBrowseHit(
                    smiles="CC=O",
                    reaction="oxidation",
                    enzyme="CYP2E1",
                    generation=1,
                ),
            ),
        ),
    ]
    w = MetaboliteBrowserWidget(None)
    w.set_records(recs)
    assert w._table.rowCount() == 2
    assert w._table.columnCount() == 5
    assert w._table.horizontalHeaderItem(2).text() == "Reaction"
    assert w._table.item(0, 0).text() == ROLE_PARENT
    assert w._table.item(1, 0).text() == ROLE_METABOLITE
    assert w._table.item(1, 2).text() == "oxidation"
    assert w._canvas_smiles == "CCO"
    assert w._canvas_kind == ROLE_PARENT
    w.close()


def test_metabolite_browser_click_shows_metabolite_on_canvas(qapp) -> None:  # noqa: ARG001
    recs = [
        MetaboliteBrowseRecord(
            oid=1,
            smiles="CCO",
            metabolites=(
                MetaboliteBrowseHit(smiles="CC=O", reaction="ox", enzyme="CYP", generation=1),
                MetaboliteBrowseHit(smiles="CC(=O)O", reaction="ox", enzyme="CYP", generation=1),
            ),
        ),
    ]
    w = MetaboliteBrowserWidget(None)
    w.set_records(recs)
    assert w._canvas_smiles == "CCO"
    w._table.selectRow(1)
    assert w._canvas_smiles == "CC=O"
    assert w._canvas_kind == ROLE_METABOLITE
    w._table.selectRow(2)
    assert w._canvas_smiles == "CC(=O)O"
    w._table.selectRow(0)
    assert w._canvas_smiles == "CCO"
    assert w._canvas_kind == ROLE_PARENT
    w.close()


def test_metabolite_browser_nav_buttons_in_footer(qapp) -> None:  # noqa: ARG001
    recs = [
        MetaboliteBrowseRecord(
            oid=1,
            smiles="CCO",
            metabolites=(MetaboliteBrowseHit(smiles="CC=O"),),
        ),
        MetaboliteBrowseRecord(
            oid=2,
            smiles="c1ccccc1",
            metabolites=(MetaboliteBrowseHit(smiles="Oc1ccccc1"),),
        ),
    ]
    w = MetaboliteBrowserWidget(None)
    w.set_records(recs)
    assert w._nav_bar is not None
    assert w._footer_bar is not None
    assert w._btn_first.text() == ""
    assert w._btn_back.text() == ""
    assert w._btn_fwd.text() == ""
    assert w._btn_last.text() == ""
    assert w._btn_select.text() == ""
    assert not w._btn_first.icon().isNull()
    assert not w._btn_back.icon().isNull()
    assert not w._btn_select.icon().isNull()
    root = w.layout()
    nav_index = root.indexOf(w._nav_bar)
    table_index = root.indexOf(w._table)
    preview_index = root.indexOf(w._preview_host)
    footer_index = root.indexOf(w._footer_bar)
    assert preview_index < table_index < nav_index < footer_index
    assert w._cb_only_selected.parent() is w._footer_bar
    assert "1 / 2" in w._meta.text()
    table_h = w._table.height()
    w._step(1)
    assert "2 / 2" in w._meta.text()
    assert w._canvas_smiles == "c1ccccc1"
    assert w._table.height() == table_h
    w._go_first()
    assert "1 / 2" in w._meta.text()
    w.close()


def test_metabolite_browser_opens_large_enough_for_2d(qapp) -> None:  # noqa: ARG001
    dlg = MetaboliteBrowserDialog(None)
    assert dlg.minimumWidth() >= 640
    assert dlg.minimumHeight() >= 780
    host = dlg._panel._preview_host
    assert host.minimumWidth() >= BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH
    assert host.minimumHeight() >= BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT
    dlg.close()


def test_metabolite_browse_session_payload_roundtrip() -> None:
    from molmanager.predictions.biotransformer_metabolites import BIOTRANSFORMER_CANCELLED
    from molmanager.ui.metabolite_browser import (
        deserialize_metabolite_browse_records,
        restore_metabolite_browse_for_session,
        serialize_metabolite_browse_records,
    )

    recs = [
        MetaboliteBrowseRecord(
            oid=4,
            smiles="c1ccccc1",
            metabolites=(
                MetaboliteBrowseHit(
                    smiles="Oc1ccccc1",
                    reaction="Hydroxylation",
                    enzyme="CYP3A4",
                    biosystem="Human",
                    generation=1,
                    precursor_smiles="c1ccccc1",
                ),
            ),
        )
    ]
    raw = serialize_metabolite_browse_records(recs)
    back = deserialize_metabolite_browse_records(raw)
    assert len(back) == 1
    hit = back[0].metabolites[0]
    assert back[0].oid == 4
    assert hit.enzyme == "CYP3A4"
    assert hit.generation == 1
    assert hit.biosystem == "Human"
    assert hit.precursor_smiles == "c1ccccc1"

    class _App:
        pass

    app = _App()
    kept = restore_metabolite_browse_for_session(
        app,
        [
            {
                "oid": 1,
                "smiles": "C",
                "error": BIOTRANSFORMER_CANCELLED,
                "metabolites": [],
            }
        ],
    )
    assert kept == 0
    assert app._metabolite_browse_records == []
