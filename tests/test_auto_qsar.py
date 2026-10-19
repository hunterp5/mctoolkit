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

"""AutoQSAR feature filtering, search isolation, and descriptor reuse."""

from __future__ import annotations

import threading

import numpy as np
import pandas as pd
import pytest

from molmanager.analysis.auto_qsar import (
    AutoQSARCancelled,
    attach_catalog_descriptors,
    filter_training_features,
    modeling_split_indices,
    search_auto_qsar,
    table_write_rows,
)
from molmanager.analysis.qsar_models import predict_qsar_rows


def _regression_frame(n: int = 40, seed: int = 0) -> tuple[pd.DataFrame, list[int]]:
    rng = np.random.default_rng(seed)
    mw = rng.uniform(200, 500, size=n)
    logp = rng.uniform(-1, 5, size=n)
    activity = 0.01 * mw + 0.8 * logp + rng.normal(0, 0.3, size=n)
    frame = pd.DataFrame({"MW": mw, "LogP": logp, "pIC50": activity})
    return frame, list(range(n))


def test_filter_drops_constant_correlated_and_ignores_holdout():
    rng = np.random.default_rng(0)
    n = 40
    signal = rng.normal(size=n)
    y = signal + rng.normal(scale=0.05, size=n)
    leak = np.zeros(n)
    leak[30:] = y[30:]
    frame = pd.DataFrame(
        {
            "signal": signal,
            "copy": signal * 1.001,
            "const": np.ones(n),
            "sparse": np.nan,
            "noise": rng.normal(size=n),
            "leak": leak,
        }
    )
    kept = filter_training_features(frame, y, np.arange(30))
    assert "const" not in kept
    assert "sparse" not in kept
    assert "leak" not in kept
    assert "noise" in kept
    assert ("signal" in kept) + ("copy" in kept) == 1


def test_selection_cv_does_not_see_holdout_labels(monkeypatch: pytest.MonkeyPatch):
    seen: list[np.ndarray] = []

    def spy(X, y, train_idx, **kwargs):  # noqa: ARG001
        seen.append(np.asarray(train_idx).copy())
        return 0.0, 0.0

    monkeypatch.setattr("molmanager.analysis.auto_qsar.score_training_matrix", spy)
    frame, oids = _regression_frame()
    search_auto_qsar(
        df=frame,
        oids=oids,
        activity_column="pIC50",
        task_mode="regression",
        effort="quick",
        mol_rows=None,
    )
    y = frame["pIC50"].to_numpy(dtype=float)
    train_idx, test_idx = modeling_split_indices(y, "regression", 0.8)
    assert seen
    for used in seen:
        assert set(used.tolist()).isdisjoint(set(test_idx.tolist()))
        assert set(used.tolist()) == set(train_idx.tolist())


def test_numeric_search_returns_a_bundle_that_predicts():
    frame, oids = _regression_frame()
    result = search_auto_qsar(
        df=frame,
        oids=oids,
        activity_column="pIC50",
        task_mode="regression",
        effort="quick",
        mol_rows=None,
    )
    assert result.winner.feature_set == "Table columns"
    assert result.fit.bundle.model is not None
    assert "not used to choose" in result.report_text
    assert "Hold-out" in result.report_text
    assert result.computed_columns_used == ()
    preds = predict_qsar_rows(
        result.fit.bundle,
        df=frame,
        oids=oids,
        mol_rows=None,
        output_column="AutoQSAR_pIC50",
    )
    assert len(preds) == len(oids)
    assert np.isfinite(float(preds[0][1]["AutoQSAR_pIC50"]))


def test_cancel_between_trials(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}
    cancel = threading.Event()

    def spy(X, y, train_idx, **kwargs):  # noqa: ARG001
        calls["n"] += 1
        cancel.set()
        return 0.1, 0.0

    monkeypatch.setattr("molmanager.analysis.auto_qsar.score_training_matrix", spy)
    frame, oids = _regression_frame()
    with pytest.raises(AutoQSARCancelled):
        search_auto_qsar(
            df=frame,
            oids=oids,
            activity_column="pIC50",
            task_mode="regression",
            effort="quick",
            mol_rows=None,
            cancel_event=cancel,
        )
    assert calls["n"] == 1


def test_attach_reuses_complete_column_and_skips_3d():
    from rdkit import Chem

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    n = 4
    frame = pd.DataFrame({"LogP": ["0.500"] * n, "pIC50": np.linspace(1, 4, n)})
    oids = list(range(n))
    mol_rows = [(oid, Chem.Mol(mol)) for oid in oids]
    attached = attach_catalog_descriptors(
        frame,
        oids,
        mol_rows,
        specs=[("LogP", "MolLogP"), ("Mol Weight", "MolWt"), ("PMI 1", "PMI1")],
    )
    assert "LogP" in attached.pool_columns
    assert "LogP" not in attached.computed_columns
    assert attached.dataframe.iloc[0]["LogP"] == "0.500"
    assert "Mol Weight" in attached.computed_columns
    assert str(attached.dataframe.iloc[0]["Mol Weight"]).startswith("46.")
    assert "PMI 1" not in attached.pool_columns
    assert any("3D descriptors skipped" in note for note in attached.notes)


def test_table_write_rows_merges_descriptors_and_predictions():
    frame = pd.DataFrame({"Mol Weight": ["46.069", "18.015"]})
    headers, rows = table_write_rows(
        frame,
        [7, 8],
        ["Mol Weight"],
        [(7, {"AutoQSAR_pIC50": "1.25"})],
        "AutoQSAR_pIC50",
    )
    assert headers == ["Mol Weight", "AutoQSAR_pIC50"]
    by_oid = dict(rows)
    assert by_oid[7]["Mol Weight"] == "46.069"
    assert by_oid[7]["AutoQSAR_pIC50"] == "1.25"
    assert by_oid[8]["Mol Weight"] == "18.015"
    assert "AutoQSAR_pIC50" not in by_oid[8]


def test_standard_effort_adds_a_second_stage(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    def spy(X, y, train_idx, **kwargs):  # noqa: ARG001
        calls["n"] += 1
        return 0.4, 0.05

    monkeypatch.setattr("molmanager.analysis.auto_qsar.score_training_matrix", spy)
    frame, oids = _regression_frame()
    result = search_auto_qsar(
        df=frame,
        oids=oids,
        activity_column="pIC50",
        task_mode="regression",
        effort="standard",
        mol_rows=None,
    )
    assert calls["n"] > 8
    assert any(trial.stage == 2 for trial in result.trials)


def test_computed_descriptor_columns_follow_the_winner(monkeypatch: pytest.MonkeyPatch):
    def spy(X, y, train_idx, **kwargs):  # noqa: ARG001
        return 0.2, 0.0

    monkeypatch.setattr("molmanager.analysis.auto_qsar.score_training_matrix", spy)
    frame, oids = _regression_frame()
    result = search_auto_qsar(
        df=frame,
        oids=oids,
        activity_column="pIC50",
        task_mode="regression",
        effort="quick",
        mol_rows=None,
        table_columns=["MW", "LogP"],
        descriptor_columns=["MW", "LogP"],
        computed_columns=["MW"],
    )
    assert result.winner.feature_set == "Computed descriptors"
    assert result.computed_columns_used == ("MW",)


def test_menu_and_help_topic_are_registered():
    from molmanager.reference.help_markdown import load_help_markdown
    from molmanager.ui.main_window.menu_spec import MAIN_WINDOW_MENUS, find_submenu

    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    qsar = find_submenu(data.items, "QSAR")
    assert [item.title for item in qsar.items] == ["Generate Model…", "AutoQSAR…", "CoMSIA…"]
    assert qsar.items[0].slot == "open_qsar_dialog"
    assert qsar.items[1].slot == "open_auto_qsar_dialog"
    text = load_help_markdown("data_auto_qsar")
    assert text is not None
    assert "hold-out" in text.lower()


def test_auto_qsar_dialog_opens(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    window = ChemistryWorkspaceWindow()
    window.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW", "pIC50"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(0, {"SMILES": "CCO", "MW": "46.07", "pIC50": "5.0"})
    window.next_oid = 1
    try:
        window.open_auto_qsar_dialog(False)
        dialog = window._auto_qsar_dialog
        assert dialog is not None
        assert dialog.windowTitle() == "AutoQSAR"
        labels = [dialog.activity_combo.itemText(i) for i in range(dialog.activity_combo.count())]
        assert "pIC50" in labels
        assert dialog.pred_column_edit.text() == "AutoQSAR_pIC50"
    finally:
        dialog = getattr(window, "_auto_qsar_dialog", None)
        if dialog is not None:
            dialog.close()
        window.close()


def test_search_worker_emits_failed_when_cancelled_before_run(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import QObject

    from molmanager.workers.auto_qsar_worker import AutoQSARSearchWorker, AutoQSARSignals

    class _Collector(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[str] = []

        def on_failed(self, message: str) -> None:
            self.messages.append(message)

    signals = AutoQSARSignals()
    collector = _Collector()
    signals.failed.connect(collector.on_failed)
    cancel = threading.Event()
    cancel.set()
    worker = AutoQSARSearchWorker({"oids": [1]}, signals, cancel_event=cancel)
    worker.run()
    assert collector.messages == ["Cancelled."]
