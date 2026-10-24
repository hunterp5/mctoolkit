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

"""Tests for BioTransformer helpers (no Java JAR required)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem

from molmanager.predictions.biotransformer_metabolites import (
    BIOTRANSFORMER_CANCELLED,
    METABOLITE_COUNT_COLUMN,
    METABOLITE_REACTIONS_COLUMN,
    METABOLITE_SMILES_COLUMN,
    SMILES_COLUMN_MAX_CHARS,
    MetaboliteHit,
    MetabolitePrediction,
    biotransformer_command,
    format_metabolite_columns,
    metabolite_output_columns,
    parse_biotransformer_sdf,
    predict_metabolites_batch,
    predict_one_smiles,
    resolve_java_heap,
    uses_cyp_mode,
)
from molmanager.platform_support.bundled_paths import (
    biotransformer_layout_errors,
    resolve_biotransformer_jar,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "biotransformer_ethanol.sdf"


def test_parse_biotransformer_sdf_skips_parent() -> None:
    hits = parse_biotransformer_sdf(FIXTURE, parent_smiles="CCO")
    assert len(hits) == 2
    smiles = {h.smiles for h in hits}
    assert "CCO" not in smiles
    by_rxn = {h.reaction: h for h in hits}
    assert "Alcohol dehydrogenase oxidation" in by_rxn
    assert by_rxn["Alcohol dehydrogenase oxidation"].enzyme == "CYP2E1"
    assert by_rxn["Alcohol dehydrogenase oxidation"].generation == 1


def test_format_metabolite_columns_truncates_and_counts() -> None:
    pred = MetabolitePrediction(
        "CCO",
        (
            MetaboliteHit("CC=O", reaction="ox"),
            MetaboliteHit("CC(=O)O", reaction="ox"),
        ),
    )
    row = format_metabolite_columns(pred)
    assert row[METABOLITE_COUNT_COLUMN] == "2"
    assert row[METABOLITE_REACTIONS_COLUMN] == "ox"
    assert "CC=O" in row[METABOLITE_SMILES_COLUMN]
    assert metabolite_output_columns()[0] == METABOLITE_COUNT_COLUMN
    empty = format_metabolite_columns(None)
    assert empty[METABOLITE_COUNT_COLUMN] == "N/A"
    err = format_metabolite_columns(MetabolitePrediction("CCO", (), error="boom"))
    assert err[METABOLITE_REACTIONS_COLUMN] == "boom"
    long_hits = tuple(MetaboliteHit("C" * 80, reaction="ox") for _ in range(40))
    trunc = format_metabolite_columns(MetabolitePrediction("C", long_hits))
    assert trunc[METABOLITE_COUNT_COLUMN] == "40"
    assert "more" in trunc[METABOLITE_SMILES_COLUMN]
    assert len(trunc[METABOLITE_SMILES_COLUMN]) <= SMILES_COLUMN_MAX_CHARS + 20


def test_uses_cyp_mode() -> None:
    assert uses_cyp_mode("cyp450")
    assert uses_cyp_mode("allHuman")
    assert not uses_cyp_mode("phaseII")


def test_biotransformer_command_includes_cyp_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites._java_reports_64bit", lambda _java: True
    )
    java = tmp_path / "java.exe"
    jar = tmp_path / "biotransformer-3.0.0.jar"
    out = tmp_path / "out.sdf"
    cmd = biotransformer_command(
        java=java,
        jar=jar,
        smiles="CCO",
        output_sdf=out,
        metabolism="cyp450",
        nsteps=2,
        cyp_mode=3,
    )
    assert cmd[:4] == [str(java), "-Xmx2g", "-jar", str(jar)]
    assert "-cm" in cmd and "3" in cmd
    assert "-s" in cmd and "2" in cmd
    phase = biotransformer_command(
        java=java,
        jar=jar,
        smiles="CCO",
        output_sdf=out,
        metabolism="phaseII",
        nsteps=1,
        cyp_mode=3,
    )
    assert "-cm" not in phase


def test_resolve_java_heap_32bit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites._java_reports_64bit", lambda _java: False
    )
    java = tmp_path / "java.exe"
    java.write_bytes(b"")
    assert resolve_java_heap(java) == "1024m"


def test_resolve_biotransformer_jar_env_and_layout(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MOLMANAGER_BIOTRANSFORMER_JAR", raising=False)
    monkeypatch.setattr(
        "molmanager.platform_support.bundled_paths.configured_biotransformer_jar_text", lambda: ""
    )
    monkeypatch.setattr(
        "molmanager.platform_support.bundled_paths.biotransformer_models_dir",
        lambda: tmp_path / "missing",
    )
    assert resolve_biotransformer_jar() is None
    jar = tmp_path / "biotransformer-3.0.0.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("MOLMANAGER_BIOTRANSFORMER_JAR", str(jar))
    assert resolve_biotransformer_jar() == jar
    errs = biotransformer_layout_errors(jar)
    assert any("database/" in e for e in errs)
    assert any("supportfiles/" in e for e in errs)
    (tmp_path / "database").mkdir()
    (tmp_path / "supportfiles").mkdir()
    layout = biotransformer_layout_errors(jar)
    assert not any("database/" in e or "supportfiles/" in e for e in layout)


def test_predict_one_smiles_uses_parsed_fixture(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "biotransformer-3.0.0.jar"
    jar.write_bytes(b"")
    (tmp_path / "database").mkdir()
    (tmp_path / "supportfiles").mkdir()
    java = tmp_path / "java.exe"
    java.write_bytes(b"")

    def fake_run(args, *, cwd, timeout_s, cancel=None, env=None):
        del timeout_s, cancel, env, cwd
        out = Path(args[args.index("-osdf") + 1])
        out.write_bytes(FIXTURE.read_bytes())
        return 0, "", ""

    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites.run_java_command", fake_run
    )
    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites.java_executable", lambda: java
    )
    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites.resolve_biotransformer_jar", lambda: jar
    )
    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites.biotransformer_layout_errors",
        lambda _jar=None: [],
    )
    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites.biotransformer_support_root",
        lambda _jar=None: tmp_path,
    )
    pred = predict_one_smiles("CCO", jar=jar, java=java)
    assert pred.error is None
    assert len(pred.metabolites) == 2


def test_predict_metabolites_batch_cancel(monkeypatch) -> None:
    calls: list[str] = []

    def fake_one(smi, **_kwargs):
        calls.append(smi)
        return MetabolitePrediction(smi, (MetaboliteHit("CC=O"),))

    monkeypatch.setattr(
        "molmanager.predictions.biotransformer_metabolites.predict_one_smiles", fake_one
    )

    def cancel() -> bool:
        return len(calls) >= 1

    out = predict_metabolites_batch(["CCO", "c1ccccc1"], cancel=cancel)
    assert out[0].metabolites
    assert out[1].error == BIOTRANSFORMER_CANCELLED


def test_biotransformer_worker_emits_columns(monkeypatch, qapp) -> None:  # noqa: ARG001
    from molmanager.workers.biotransformer_worker import (
        BiotransformerRequest,
        BiotransformerSignals,
        BiotransformerWorker,
    )
    from molmanager.workers.signals import WorkerSignals

    finished: list = []
    failed: list = []
    sig = BiotransformerSignals()
    sig.finished.connect(lambda rows: finished.append(rows))
    sig.failed.connect(lambda msg: failed.append(msg))

    def fake_batch(smiles, **_kwargs):
        return [
            MetabolitePrediction(
                smi,
                (MetaboliteHit("CC=O", reaction="ox", enzyme="CYP2E1", generation=1),),
            )
            for smi in smiles
        ]

    monkeypatch.setattr(
        "molmanager.workers.biotransformer_worker.predict_metabolites_batch", fake_batch
    )
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    BiotransformerWorker(BiotransformerRequest(rows=[(1, mol)]), WorkerSignals(), sig).run()
    assert failed == []
    assert finished
    oid, cols, hits, headers, add, parent = finished[0][0]
    assert oid == 1
    assert cols[METABOLITE_COUNT_COLUMN] == "1"
    assert hits[0]["smiles"]
    assert METABOLITE_SMILES_COLUMN in headers
    assert add is False
    assert parent


def test_records_from_worker_rows_skips_cancelled() -> None:
    from molmanager.ui.metabolite_browser import records_from_worker_rows

    rows = [
        (
            1,
            {METABOLITE_COUNT_COLUMN: "1", METABOLITE_REACTIONS_COLUMN: "ox"},
            [{"smiles": "CC=O", "reaction": "ox", "generation": 1}],
            metabolite_output_columns(),
            False,
            "CCO",
        ),
        (
            2,
            {METABOLITE_REACTIONS_COLUMN: BIOTRANSFORMER_CANCELLED},
            [],
            metabolite_output_columns(),
            False,
            "c1ccccc1",
        ),
    ]
    recs = records_from_worker_rows(rows)
    assert len(recs) == 1
    assert recs[0].metabolites[0].smiles == "CC=O"


def test_unknown_metabolism_raises() -> None:
    with pytest.raises(ValueError, match="Unknown BioTransformer"):
        predict_metabolites_batch(["CCO"], metabolism="envimicro")  # type: ignore[arg-type]


def test_biotransformer_dialog_warns_on_predict_when_missing(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.predictions.biotransformer_metabolites import CYP_MODE_LABELS, DEFAULT_CYP_MODE
    from molmanager.ui.dialogs.biotransformer import BiotransformerDialog

    monkeypatch.setattr(
        "molmanager.ui.dialogs.biotransformer.install_ready_message",
        lambda: "Java is not on PATH.",
    )
    shown: list[str] = []

    def _warn(_parent, _title, text, *_args, **_kwargs):
        shown.append(text)
        return QMessageBox.Ok

    monkeypatch.setattr("molmanager.ui.dialogs.biotransformer.QMessageBox.warning", _warn)
    dlg = BiotransformerDialog(None)
    assert [dlg.cyp_combo.itemData(i) for i in range(dlg.cyp_combo.count())] == [
        v for v, _ in CYP_MODE_LABELS
    ]
    assert dlg.cyp_combo.currentData() == DEFAULT_CYP_MODE
    assert dlg.predict_btn.isEnabled()
    assert dlg.browse_btn.isEnabled()
    dlg.predict_btn.click()
    assert shown == ["Java is not on PATH."]
    dlg.subset_combo.setCurrentIndex(
        next(
            i for i in range(dlg.subset_combo.count()) if dlg.subset_combo.itemData(i) == "phaseII"
        )
    )
    assert not dlg.cyp_combo.isEnabled()
    dlg.close()


def test_is_metabolite_column_header_and_parse_smiles() -> None:
    from molmanager.predictions.biotransformer_metabolites import (
        is_metabolite_column_header,
        parse_metabolite_smiles_cell,
    )

    assert is_metabolite_column_header("Metabolite SMILES", METABOLITE_SMILES_COLUMN)
    assert is_metabolite_column_header("Metabolite SMILES (1)", METABOLITE_SMILES_COLUMN)
    assert not is_metabolite_column_header("SMILES", METABOLITE_SMILES_COLUMN)
    assert parse_metabolite_smiles_cell("CCO; CC=O") == ["CCO", "CC=O"]
    assert parse_metabolite_smiles_cell("CCO; CC=O (+3 more)") == ["CCO", "CC=O"]
    assert parse_metabolite_smiles_cell("N/A") == []


def test_metabolite_records_from_table(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.metabolite_browser import records_from_table

    w = ChemistryWorkspaceWindow()
    w.headers = [
        "ID_HIDDEN",
        "Structure",
        "SMILES",
        METABOLITE_COUNT_COLUMN,
        METABOLITE_REACTIONS_COLUMN,
        METABOLITE_SMILES_COLUMN,
    ]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(
        0,
        {
            "SMILES": "CCO",
            METABOLITE_COUNT_COLUMN: "2",
            METABOLITE_REACTIONS_COLUMN: "ox",
            METABOLITE_SMILES_COLUMN: "CC=O; CCO",
        },
    )
    w._table_model.append_row(
        1,
        {
            "SMILES": "c1ccccc1",
            METABOLITE_COUNT_COLUMN: "N/A",
            METABOLITE_REACTIONS_COLUMN: "N/A",
            METABOLITE_SMILES_COLUMN: "N/A",
        },
    )
    recs = records_from_table(w)
    assert len(recs) == 1
    assert recs[0].oid == 0
    assert recs[0].smiles == "CCO"
    assert [h.smiles for h in recs[0].metabolites] == ["CC=O", "CCO"]
    w.close()
