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

"""REINVENT 4 staged-learning config, summary parsing, and the subprocess wrapper."""

from __future__ import annotations

import sys
from pathlib import Path

from molmanager.generative.reinvent_learning import (
    LearningRequest,
    execute_learning,
    outcome_from_summary,
    parse_learning_csv,
    render_learning_toml,
    validate_request,
    write_learning_inputs,
)


def _request(**overrides) -> LearningRequest:
    base = dict(
        generator="denovo",
        model_file=".reinvent",
        device="cpu",
        batch_size=32,
        max_steps=10,
        min_steps=2,
        max_score=0.6,
        sigma=128,
        rate=0.0001,
        randomize_smiles=True,
        diversity_filter=True,
        aggregation="geometric_mean",
        keep=5,
        qed=True,
        molecular_weight=True,
        mw_low=200,
        mw_high=500,
        slogp=False,
        slogp_low=1,
        slogp_high=4,
        sa_score=False,
        similarity=False,
        similarity_smiles=(),
        unwanted_groups=True,
        extra_smarts=(),
        sample_strategy="",
        temperature=1.0,
        distance_threshold=100,
        seeds=(),
        agent_output="",
    )
    base.update(overrides)
    return LearningRequest(**base)


def _fake_reinvent(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_reinvent.py"
    script.write_text(body, encoding="utf-8")
    if sys.platform == "win32":
        command = tmp_path / "reinvent.cmd"
        command.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
        return command
    command = tmp_path / "reinvent"
    command.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
        encoding="utf-8",
    )
    command.chmod(0o755)
    return command


def test_denovo_toml_is_one_qed_and_weight_stage(tmp_path: Path) -> None:
    text = render_learning_toml(
        _request(),
        summary_prefix=tmp_path / "summary",
        checkpoint=tmp_path / "agent.chkpt",
        smiles_file=None,
    )
    assert 'run_type = "staged_learning"' in text
    assert "prior_file = " in text and ".reinvent" in text
    assert "agent_file = " in text
    assert "smiles_file" not in text
    assert "unique_sequences" not in text
    assert "purge_memories = false" in text
    assert "sample_strategy" not in text
    assert "[stage.scoring.component.Qed]" in text
    assert "[stage.scoring.component.MolecularWeight]" in text
    assert "transform.low = 200.0" in text
    assert "transform.high = 500.0" in text
    assert "[stage.scoring.component.CustomAlerts]" in text
    assert "[diversity_filter]" in text
    assert 'type = "IdenticalMurckoScaffold"' in text
    assert "max_steps = 10" in text
    assert "min_steps = 2" in text


def test_libinvent_toml_includes_seeds_and_mol2mol_options(tmp_path: Path) -> None:
    lib = render_learning_toml(
        _request(generator="libinvent", model_file=".libinvent", seeds=("*c1ccccc1",)),
        summary_prefix=tmp_path / "summary",
        checkpoint=tmp_path / "agent.chkpt",
        smiles_file=tmp_path / "seeds.smi",
    )
    assert 'smiles_file = "' in lib
    assert "sample_strategy" not in lib

    mol2mol = render_learning_toml(
        _request(
            generator="mol2mol",
            model_file=".m2m_similarity",
            sample_strategy="multinomial",
            temperature=0.8,
            distance_threshold=80,
            seeds=("CCO",),
            similarity=True,
            similarity_smiles=("CCO", "c1ccccc1"),
            qed=False,
            molecular_weight=False,
            unwanted_groups=False,
        ),
        summary_prefix=tmp_path / "summary",
        checkpoint=tmp_path / "agent.chkpt",
        smiles_file=tmp_path / "seeds.smi",
    )
    assert 'sample_strategy = "multinomial"' in mol2mol
    assert "temperature = 0.8" in mol2mol
    assert "distance_threshold = 80" in mol2mol
    assert mol2mol.count("[[stage.scoring.component.TanimotoSimilarity.endpoint]]") == 2
    assert "[diversity_filter]" not in render_learning_toml(
        _request(diversity_filter=False),
        summary_prefix=tmp_path / "summary",
        checkpoint=tmp_path / "agent.chkpt",
        smiles_file=None,
    )


def test_validate_request_rejects_an_empty_score_and_a_bad_window() -> None:
    assert validate_request(_request()) is None
    assert "at least one score" in validate_request(
        _request(qed=False, molecular_weight=False, unwanted_groups=False)
    )
    assert "low value" in validate_request(_request(mw_low=500, mw_high=200))
    assert "cannot exceed" in validate_request(_request(min_steps=20, max_steps=5))
    missing = validate_request(_request(similarity=True, similarity_smiles=()))
    assert missing is not None and "reference" in missing


def test_summary_keeps_the_highest_score_and_the_keep_limit(tmp_path: Path) -> None:
    path = tmp_path / "summary_1.csv"
    path.write_text(
        "Agent,Prior,Target,Score,SMILES,SMILES_state,QED,QED (raw),step\n"
        "1.0,2.0,3.0,0.2000000,CCO,1,0.2000000,0.2000,1\n"
        "1.0,2.0,3.0,0.9000000,CCO,1,0.9000000,0.9000,4\n"
        "1.0,2.0,3.0,0.5000000,c1ccccc1,1,0.5000000,0.5000,2\n"
        "1.0,2.0,3.0,0.8000000,not-a-molecule,0,0.8000000,0.8000,3\n"
        "1.0,2.0,3.0,0.4000000,CCN,1,0.4000000,0.4000,2\n",
        encoding="utf-8",
    )
    rows, skipped = parse_learning_csv(path)
    assert skipped == 1
    assert len(rows) == 4
    outcome = outcome_from_summary(path, _request(keep=2), cancelled=False)
    assert [smiles for smiles, _fields in outcome.records] == ["CCO", "c1ccccc1"]
    assert outcome.records[0][1]["REINVENT_Score"] == "0.9000"
    assert outcome.records[0][1]["REINVENT_Step"] == "4"
    assert outcome.records[0][1]["REINVENT_QED"] == "0.9000000"
    assert "REINVENT_QED_raw" not in outcome.records[0][1]
    assert outcome.skipped_invalid == 1


def test_execute_learning_reads_the_summary_and_copies_the_agent(tmp_path: Path) -> None:
    body = """
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[-1]).read_text(encoding="utf-8")
prefix = re.search(r'summary_csv_prefix = "([^"]+)"', text).group(1)
chkpt = re.search(r'chkpt_file = "([^"]+)"', text).group(1)
pathlib.Path(prefix + "_1.csv").write_text(
    "Agent,Prior,Target,Score,SMILES,SMILES_state,step\\n"
    "1,2,3,0.7000000,CCO,1,1\\n",
    encoding="utf-8",
)
pathlib.Path(chkpt).write_text("agent", encoding="utf-8")
print("learned", flush=True)
"""
    executable = _fake_reinvent(tmp_path, body)
    agent = tmp_path / "out" / "agent.chkpt"
    logs: list[str] = []
    outcome = execute_learning(
        str(executable),
        _request(agent_output=str(agent), keep=10),
        on_log=logs.append,
        work_dir=tmp_path / "work",
    )
    assert outcome.records[0][0] == "CCO"
    assert agent.read_text(encoding="utf-8") == "agent"
    assert any("learned" in line for line in logs)
    assert (tmp_path / "work" / "staged_learning.toml").is_file()


def test_scaffold_smarts_is_a_scoring_term_and_filters_rows(tmp_path: Path) -> None:
    text = render_learning_toml(
        _request(scaffold_smarts="c1ccccc1", qed=True),
        summary_prefix=tmp_path / "summary",
        checkpoint=tmp_path / "agent.chkpt",
        smiles_file=None,
    )
    assert "[stage.scoring.component.MatchingSubstructure]" in text
    assert 'params.smarts = ["c1ccccc1"]' in text
    path = tmp_path / "summary_1.csv"
    path.write_text(
        "Agent,Prior,Target,Score,SMILES,SMILES_state,step\n"
        "1,2,3,0.9000000,c1ccccc1,1,2\n"
        "1,2,3,0.8000000,CCO,1,2\n",
        encoding="utf-8",
    )
    outcome = outcome_from_summary(
        path,
        _request(scaffold_smarts="c1ccccc1", keep=10),
        cancelled=False,
    )
    assert [smiles for smiles, _fields in outcome.records] == ["c1ccccc1"]
    assert outcome.skipped_scaffold == 1
    assert (
        validate_request(
            _request(
                generator="libinvent",
                model_file=".libinvent",
                seeds=(),
                scaffold_smarts="*c1ccccc1",
            )
        )
        is None
    )


def test_write_inputs_and_dialog_defaults(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    config, summary, checkpoint = write_learning_inputs(tmp_path, _request())
    text = config.read_text(encoding="utf-8")
    assert summary.name == "summary_1.csv"
    assert checkpoint.name == "agent.chkpt"
    assert "summary_csv_prefix" in text
    assert not text.startswith("\ufeff")

    from molmanager.ui.dialogs.reinvent_learning import ReinventLearningDialog

    dialog = ReinventLearningDialog(None)
    request = dialog.request()
    assert request.generator == "denovo"
    assert request.model_file == ".reinvent"
    assert request.qed is True
    assert request.molecular_weight is True
    assert request.similarity is False
    assert request.scaffold_smarts == ""
    dialog.scaffold_edit.setText("c1ccccc1")
    assert dialog.request().scaffold_smarts == "c1ccccc1"
    assert dialog.scaffold_sketch.text() == "Sketcher…"
    assert dialog.seed_box.isHidden()
    assert dialog.reference_box.isHidden()
    dialog.generator_combo.setCurrentIndex(1)
    assert dialog.request().generator == "libinvent"
    assert dialog.request().model_file == ".libinvent"
    assert not dialog.seed_box.isHidden()
    dialog.model_edit.setText(r"C:\models\custom.prior")
    dialog.generator_combo.setCurrentIndex(3)
    assert dialog.model_edit.text().endswith("custom.prior")
    assert not dialog.temperature_spin.isHidden()
    dialog.similarity_check.setChecked(True)
    assert not dialog.reference_box.isHidden()
    request = dialog.request()
    assert request.diversity_type == "IdenticalMurckoScaffold"
    assert request.diversity_bucket == 25
    assert request.qed_weight == 1.0
    assert request.seed == 0
    assert request.extra_flags == ""
    dialog.diversity_type.setCurrentIndex(dialog.diversity_type.findData("PenalizeSameSmiles"))
    assert dialog.diversity_bucket.isHidden()
    assert not dialog.diversity_penalty.isHidden()
    dialog.qed_weight_spin.setValue(2.5)
    dialog.extra_flags_edit.setText("--seed 4")
    assert dialog.request().qed_weight == 2.5
    assert dialog.request().extra_flags == "--seed 4"
    dialog.close()


def test_optional_learning_fields_reach_the_toml(tmp_path: Path) -> None:
    text = render_learning_toml(
        _request(
            qed=False,
            molecular_weight=False,
            unwanted_groups=False,
            similarity=True,
            similarity_smiles=("CCO",),
            similarity_weight=2.5,
            similarity_radius=3,
            similarity_counts=True,
            diversity_type="ScaffoldSimilarity",
            diversity_bucket=10,
            diversity_minscore=0.2,
            diversity_minsimilarity=0.6,
            seed=4,
            isomeric_smiles=True,
        ),
        summary_prefix=tmp_path / "summary",
        checkpoint=tmp_path / "agent.chkpt",
        smiles_file=None,
    )
    assert 'type = "ScaffoldSimilarity"' in text
    assert "bucket_size = 10" in text
    assert "minscore = 0.2" in text
    assert "minsimilarity = 0.6" in text
    assert "weight = 2.5" in text
    assert "params.radius = 3" in text
    assert "params.use_counts = true" in text
    assert "seed = 4" in text
    assert "isomeric_smiles = true" in text
    assert validate_request(_request(extra_flags="rm -rf")) is not None
    assert validate_request(_request(qed_weight=-1)) is not None
