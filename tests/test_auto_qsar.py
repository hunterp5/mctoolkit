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

"""Dixon AutoQSAR score, descriptor filter, consensus, and dialog wiring."""

from __future__ import annotations

import inspect
import threading

import numpy as np
import pandas as pd
import pytest

from molmanager.analysis.auto_qsar import (
    DESCRIPTOR_SET,
    AutoQSARCancelled,
    AutoQSARModel,
    AutoQSARResult,
    FeatureBlock,
    _consensus_class,
    effort_settings,
    methods_for,
    output_headers,
    predict_auto_qsar,
    search_auto_qsar,
    table_write_rows,
)
from molmanager.analysis.auto_qsar_features import (
    EXCLUDED_RDKIT_DESCRIPTORS,
    _cluster_representatives,
    rdkit_descriptor_names,
    select_descriptor_columns,
)
from molmanager.analysis.auto_qsar_models import (
    conformal_half_width,
    dixon_score,
    latent_factors_before_r2_cap,
    subset_size_limit,
)


def _regression_frame(n: int = 12) -> tuple[pd.DataFrame, list[int]]:
    activity = np.linspace(1.0, 4.0, n)
    width = np.linspace(10.0, 30.0, n)
    frame = pd.DataFrame({"Width": width, "pIC50": activity})
    return frame, list(range(n))


def _columns_with_correlation(correlation: float, n: int = 40) -> np.ndarray:
    index = np.arange(n, dtype=float)
    left = index - index.mean()
    noise = np.sin(np.linspace(0.0, 2.0 * np.pi, n, endpoint=False))
    noise = noise - noise.mean()
    noise = noise - left * np.dot(left, noise) / np.dot(left, left)
    left = left / np.linalg.norm(left)
    noise = noise / np.linalg.norm(noise)
    right = correlation * left + np.sqrt(1.0 - correlation * correlation) * noise
    return np.column_stack([left, right])


def test_descriptor_filter_drops_identical_and_low_variance_without_activity():
    assert "y" not in inspect.signature(select_descriptor_columns).parameters
    n = 20
    varied = np.linspace(0.0, 5.0, n)
    copied = varied * 2.0
    constant = np.ones(n)
    mostly_identical = np.zeros(n)
    mostly_identical[-1] = 4.0
    tiny = np.full(n, 2.0)
    tiny += np.linspace(0.0, 1e-15, n)
    other = np.array([1.0, -1.0] * (n // 2))
    matrix = np.column_stack([varied, copied, constant, mostly_identical, tiny, other])
    _rows, columns, _note = select_descriptor_columns(matrix)
    kept = set(columns.tolist())
    assert 2 not in kept
    assert 3 not in kept
    assert 4 not in kept
    assert len(kept & {0, 1}) == 1
    assert 5 in kept

    edge = np.zeros((n, 1))
    edge[:3, 0] = [1.0, 2.0, 3.0]
    _rows, edge_columns, _note = select_descriptor_columns(edge)
    assert edge_columns.tolist() == [0]


def test_selected_table_columns_join_the_descriptor_pool():
    frame, oids = _regression_frame()
    included = search_auto_qsar(
        df=frame,
        oids=oids,
        activity_column="pIC50",
        task_mode="regression",
        effort="quick",
        mol_rows=None,
        table_columns=["Width"],
    )
    assert "Width" in included.blocks[DESCRIPTOR_SET].columns
    with pytest.raises(ValueError, match="selected table column"):
        search_auto_qsar(
            df=frame,
            oids=oids,
            activity_column="pIC50",
            task_mode="regression",
            effort="quick",
            mol_rows=None,
            table_columns=[],
        )


def test_correlation_clusters_follow_the_dixon_cutoff():
    perfect = np.column_stack([np.linspace(0.0, 1.0, 30), np.linspace(2.0, 4.0, 30)])
    assert _cluster_representatives(perfect) == [0] or _cluster_representatives(perfect) == [1]
    assert len(_cluster_representatives(perfect)) == 1

    above = _columns_with_correlation(0.81)
    below = _columns_with_correlation(0.79)
    assert abs(float(np.corrcoef(above, rowvar=False)[0, 1])) > 0.8
    assert abs(float(np.corrcoef(below, rowvar=False)[0, 1])) < 0.8
    assert len(_cluster_representatives(above)) == 1
    assert len(_cluster_representatives(below)) == 2


def test_dixon_score_latent_cap_and_subset_limit():
    assert dixon_score(0.95, -0.4) == pytest.approx(-0.4)
    assert dixon_score(0.9, 0.7) == pytest.approx(0.56)
    assert latent_factors_before_r2_cap([0.5, 0.8, 0.95]) == 2
    assert latent_factors_before_r2_cap([0.95, 0.99]) == 1
    assert latent_factors_before_r2_cap([0.2, 0.4, 0.6]) == 3
    assert subset_size_limit(30) == 3
    assert subset_size_limit(6) == 1
    assert subset_size_limit(1000) == 40
    residuals = np.array([0.1, 0.4, 0.2, 1.0])
    assert conformal_half_width(residuals) == pytest.approx(1.0)


def test_excluded_descriptors_and_method_grid():
    names = set(rdkit_descriptor_names())
    assert EXCLUDED_RDKIT_DESCRIPTORS.isdisjoint(names)
    assert "MolWt" in names
    assert "AvgIpc" in names
    assert "pls" not in methods_for("regression", "fingerprints")
    assert "kpls" in methods_for("regression", "descriptors")
    assert "kpls" in methods_for("regression", "fingerprints")
    assert "mlr" not in methods_for("regression", "fingerprints")
    assert "rp" in methods_for("classification", "descriptors")
    assert methods_for("classification", "fingerprints") == ("bayes",)
    quick = effort_settings("quick")
    standard = effort_settings("standard")
    assert (quick.splits, quick.retain) == (10, 5)
    assert (standard.splits, standard.retain) == (50, 10)


def test_consensus_mean_and_majority_vote():
    block = FeatureBlock(
        name=DESCRIPTOR_SET,
        kind="descriptors",
        columns=("X",),
        bit_ids=np.array([], dtype=np.int64),
        fingerprint_kind="",
        values=np.arange(8, dtype=float).reshape(-1, 1),
        requires_structure=False,
    )

    def model(value: float, half: float, inside: bool) -> AutoQSARModel:
        class _Constant:
            def predict(self, values, train=None):
                return np.full(values.shape[0], value, dtype=float)

            def domain_mask(self, values, train=None):
                return np.full(values.shape[0], inside)

        return AutoQSARModel(
            method="pls",
            method_label="PLS",
            feature_set=DESCRIPTOR_SET,
            score=0.5,
            train_accuracy=0.6,
            test_accuracy=0.5,
            split_index=0,
            n_features=1,
            train_index=np.arange(6),
            estimator=_Constant(),
            half_width=half,
        )

    result = AutoQSARResult(
        task="regression",
        effort="quick",
        activity_column="Y",
        n_built=2,
        n_attempted=2,
        models=(model(1.0, 0.2, True), model(3.0, 0.4, False)),
        blocks={DESCRIPTOR_SET: block},
        class_labels=None,
        learning_oids=tuple(range(8)),
        write_columns=(),
        report_text="",
        notes=(),
    )
    frame = pd.DataFrame({"X": [1.0, 2.0], "Y": [0.0, 0.0]})
    rows = predict_auto_qsar(result, df=frame, oids=[10, 11], mol_rows=None, output_column="Pred")
    assert rows[0][1]["Pred"] == "2"
    assert rows[0][1]["Pred interval"] == "0.3"
    assert rows[0][1]["Pred domain"] == "in"
    lone = predict_auto_qsar(
        result,
        df=frame,
        oids=[10, 11],
        mol_rows=None,
        output_column="Pred",
        model_index=1,
    )
    assert lone[0][1]["Pred"] == "3"
    assert lone[0][1]["Pred domain"] == "out"
    code, probability = _consensus_class(
        [0, 0, 1],
        [{0: 0.6, 1: 0.4}, {0: 0.7, 1: 0.3}, {0: 0.2, 1: 0.8}],
    )
    assert code == 0
    assert probability == pytest.approx(2.0 / 3.0)
    tied, tied_probability = _consensus_class(
        [0, 1],
        [{0: 0.2, 1: 0.8}, {0: 0.9, 1: 0.1}],
    )
    assert tied == 0
    assert tied_probability == pytest.approx(0.55)


def test_quick_regression_scores_a_row_outside_the_learning_set():
    from rdkit import Chem

    smiles = [
        "CCO",
        "CCN",
        "CCC",
        "c1ccccc1",
        "CC(=O)O",
        "CCN(CC)CC",
        "c1ccncc1",
        "CC(C)O",
        "CCOC",
    ]
    mols = [Chem.MolFromSmiles(smiles_text) for smiles_text in smiles]
    assert all(mol is not None for mol in mols)
    activity = np.linspace(1.0, 5.0, 8)
    frame = pd.DataFrame({"pIC50": list(activity) + [np.nan]})
    oids = list(range(9))
    mol_rows = [(oid, mols[oid]) for oid in oids]
    progress: list[tuple[int, int]] = []

    def on_progress(done: int, total: int, _message: str) -> None:
        progress.append((done, total))

    result = search_auto_qsar(
        df=frame,
        oids=oids,
        activity_column="pIC50",
        task_mode="regression",
        effort="quick",
        mol_rows=mol_rows,
        on_progress=on_progress,
    )
    assert result.effort == "quick"
    assert len(result.models) <= 5
    assert result.models
    assert 8 not in result.learning_oids
    assert "consensus" in result.report_text.lower()
    assert "domain" in result.report_text.lower()
    assert progress
    assert all(progress[i][0] <= progress[i + 1][0] for i in range(len(progress) - 1))
    preds = predict_auto_qsar(
        result,
        df=frame,
        oids=oids,
        mol_rows=mol_rows,
        output_column="AutoQSAR_pIC50",
    )
    by_oid = dict(preds)
    assert 8 in by_oid
    assert np.isfinite(float(by_oid[8]["AutoQSAR_pIC50"]))
    assert by_oid[8]["AutoQSAR_pIC50 domain"] in {"in", "out"}
    assert "AutoQSAR_pIC50 interval" in by_oid[8]
    headers = output_headers("AutoQSAR_pIC50", "regression", result.write_columns)
    written, rows = table_write_rows(preds, headers)
    assert written[-3:] == ["AutoQSAR_pIC50", "AutoQSAR_pIC50 interval", "AutoQSAR_pIC50 domain"]
    assert dict(rows)[8]["AutoQSAR_pIC50 domain"] in {"in", "out"}


def test_cancel_before_and_between_models(monkeypatch: pytest.MonkeyPatch):
    frame, oids = _regression_frame()
    cancel = threading.Event()
    cancel.set()
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

    calls = {"n": 0}
    between = threading.Event()

    def spy(*_args, **_kwargs):
        calls["n"] += 1
        between.set()
        raise ValueError("stop after the first model")

    monkeypatch.setattr("molmanager.analysis.auto_qsar.fit_split_model", spy)
    with pytest.raises(AutoQSARCancelled):
        search_auto_qsar(
            df=frame,
            oids=oids,
            activity_column="pIC50",
            task_mode="regression",
            effort="quick",
            mol_rows=None,
            table_columns=["Width"],
            cancel_event=between,
        )
    assert calls["n"] == 1


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
    lowered = text.lower()
    assert "consensus" in lowered
    assert "score" in lowered
    assert "domain" in lowered


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
        assert dialog.chk_consensus.isChecked()
        from PyQt5.QtCore import Qt

        names = [dialog.column_list.item(i).text() for i in range(dialog.column_list.count())]
        assert "MW" in names
        mw = dialog.column_list.item(names.index("MW"))
        assert mw.checkState() == Qt.Unchecked
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
