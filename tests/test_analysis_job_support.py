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

"""Unit tests for analysis_job_support helpers (no full GUI)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from molmanager.platform_support.tool_progress import ToolProgressState
from molmanager.ui.analysis_job_support import (
    enqueue_process_queue_job,
    ensure_table_ready_for_tool,
    finish_analysis_pairs,
    prepare_scoped_structure_mols,
    prepare_scoped_structure_payloads,
    report_analysis_failure,
    report_cancellable_job_failure,
)


def test_finish_analysis_pairs_empty_returns_none(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    assert finish_analysis_pairs(app, "Tool", [], empty_message="none") is None
    app._finish_tool_progress.assert_called_once_with("Tool", job_id=None)
    assert infos and infos[0][2] == "none"


def test_finish_analysis_pairs_returns_list(monkeypatch):
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: None,
    )
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    out = finish_analysis_pairs(app, "Tool", [1, 2], empty_message="none")
    assert out == [1, 2]


def test_report_analysis_failure(monkeypatch):
    warns: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.warning",
        lambda *a, **k: warns.append(a),
    )
    app = SimpleNamespace(
        _clear_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    report_analysis_failure(app, "Tool", "", fallback="failed")
    app._clear_tool_progress.assert_called_once()
    assert warns and warns[0][2] == "failed"


def test_ensure_table_ready_for_tool_no_headers(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app = SimpleNamespace(headers=[], _table_model=SimpleNamespace(rowCount=lambda: 0))
    assert ensure_table_ready_for_tool(app, "Cluster") is False
    assert infos


def test_ensure_table_ready_for_tool_ok():
    app = SimpleNamespace(headers=["SMILES"], _table_model=SimpleNamespace(rowCount=lambda: 1))
    assert ensure_table_ready_for_tool(app, "Cluster") is True


def test_prepare_scoped_structure_mols_empty_selection(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app = SimpleNamespace(
        _abort_if_only_selected_but_empty=MagicMock(return_value=True),
        _selected_oids_set=MagicMock(return_value=set()),
        collect_scoped_table_mols=MagicMock(),
    )
    assert (
        prepare_scoped_structure_mols(
            app,
            tool_label="Cluster",
            structure_source="SMILES",
            only_selected=True,
        )
        is None
    )
    app.collect_scoped_table_mols.assert_not_called()


def _one_row_app(source_values: dict[str, str], structures: list[tuple[int, bytes | None, str]]):
    class _Model:
        def rowCount(self) -> int:
            return 1

        def row_oid(self, row: int) -> int:
            del row
            return 1

        def backing_value_for_row_header(self, row: int, header: str) -> str:
            del row
            return source_values.get(header, "")

        def is_pixmap_data_column(self, header: str) -> bool:
            del header
            return False

    class _Mols:
        def __init__(self) -> None:
            self.batch_calls = 0
            self.scan_calls = 0

        def structure_payloads_for(self, oids):
            self.batch_calls += 1
            wanted = {int(oid) for oid in oids}
            for oid, blob, smiles in structures:
                if int(oid) in wanted:
                    yield oid, blob, smiles

        def iter_structure_payloads(self):
            self.scan_calls += 1
            yield from structures

        def structure_text_for(self, oid: int) -> str:
            del oid
            return ""

        def blob_for(self, oid: int) -> bytes | None:
            del oid
            return None

    mols = _Mols()
    app = SimpleNamespace(
        headers=["ID_HIDDEN", "Structure", "SMILES"],
        _table_model=_Model(),
        _table_cell_text=lambda row, col: "",
        logical_row_for_oid=lambda oid: 0 if int(oid) == 1 else -1,
        mols=mols,
        _selected_oids_set=lambda: set(),
        _abort_if_only_selected_but_empty=lambda *_a, **_k: False,
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    return app, mols


def test_prepare_scoped_structure_mols_too_few(monkeypatch):
    infos: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    app, mols = _one_row_app({"SMILES": "CCO"}, [])
    assert (
        prepare_scoped_structure_mols(
            app,
            tool_label="Cluster",
            structure_source="SMILES",
            only_selected=False,
            min_mols=2,
            too_few_message="need two",
        )
        is None
    )
    assert infos and infos[0][2] == "need two"
    assert mols.batch_calls == 0
    assert mols.scan_calls == 0


def test_prepare_scoped_structure_payloads_batches_the_molecule_store(monkeypatch):
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.information",
        lambda *a, **k: None,
    )
    app, mols = _one_row_app({}, [(1, b"blob", "CCO")])
    out = prepare_scoped_structure_payloads(
        app,
        tool_label="Cluster",
        structure_source="Structure",
        only_selected=False,
    )
    assert out is not None
    assert [(payload.oid, payload.smiles, payload.blob) for payload in out] == [(1, "CCO", b"blob")]
    assert mols.scan_calls == 1
    assert mols.batch_calls == 0


def test_enqueue_process_queue_job_returns_id():
    state = ToolProgressState()
    app = SimpleNamespace(
        _begin_tool_progress=MagicMock(),
        _tool_progress_state=state,
        process_queue=SimpleNamespace(enqueue=MagicMock(return_value="job-1")),
    )
    factory = MagicMock()
    assert (
        enqueue_process_queue_job(app, "Clustering", 3, factory, queue_label="Cluster (3)")
        == "job-1"
    )
    assert app._begin_tool_progress.call_count == 1
    begin_args, begin_kwargs = app._begin_tool_progress.call_args
    assert begin_args[:2] == ("Clustering", 3)
    assert "job_id" in begin_kwargs
    enqueue_args, enqueue_kwargs = app.process_queue.enqueue.call_args
    assert enqueue_args[0] == "Cluster (3)"
    assert enqueue_kwargs.get("job_id") == begin_kwargs["job_id"]
    wrapped = enqueue_args[1]
    wrapped("cancel-ev")
    factory.assert_called_once()
    assert factory.call_args.args[0] == "cancel-ev"
    # Second arg is a BoundToolProgress for the allocated job id.
    assert getattr(factory.call_args.args[1], "_job_id", None) == begin_kwargs["job_id"]


def test_report_cancellable_job_failure_cancelled(monkeypatch):
    warns: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.warning",
        lambda *a, **k: warns.append(a),
    )
    after = MagicMock()
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
        _consume_partial_results_notice=MagicMock(return_value="Partial kept."),
    )
    report_cancellable_job_failure(
        app,
        "Cluster",
        "Cancelled.",
        progress_label="Clustering",
        failure_fallback="failed",
        after_finish=after,
    )
    after.assert_called_once()
    app.status_label.setText.assert_called_once_with("Partial kept.")
    assert not warns


def test_report_cancellable_job_failure_error(monkeypatch):
    warns: list[tuple] = []
    monkeypatch.setattr(
        "molmanager.ui.analysis_job_support.QMessageBox.warning",
        lambda *a, **k: warns.append(a),
    )
    app = SimpleNamespace(
        _finish_tool_progress=MagicMock(),
        status_label=SimpleNamespace(setText=MagicMock()),
    )
    report_cancellable_job_failure(
        app,
        "Cluster",
        "boom",
        progress_label="Clustering",
        failure_fallback="failed",
    )
    assert warns and warns[0][2] == "boom"
