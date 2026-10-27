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

"""REINVENT 4 sampling config, CSV parsing, and the subprocess wrapper."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from molmanager.generative.reinvent_sampling import (
    SamplingRequest,
    describe_reinvent,
    execute_sampling,
    normalize_seed_lines,
    outcome_from_csv,
    parse_extra_flags,
    parse_sampling_csv,
    render_sampling_toml,
    seed_text_for_row,
    validate_request,
    validate_seeds,
    write_sampling_inputs,
)


def _request(**overrides) -> SamplingRequest:
    base = dict(
        generator="denovo",
        model_file=".reinvent",
        num_smiles=10,
        device="cpu",
        unique_molecules=True,
        randomize_smiles=False,
        sample_strategy="",
        temperature=1.0,
        seeds=(),
    )
    base.update(overrides)
    return SamplingRequest(**base)


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


def test_denovo_toml_omits_seeds_and_transformer_options(tmp_path: Path) -> None:
    text = render_sampling_toml(
        _request(),
        output_file=tmp_path / "sampling.csv",
        smiles_file=None,
    )
    assert 'run_type = "sampling"' in text
    assert 'model_file = ".reinvent"' in text
    assert "num_smiles = 10" in text
    assert "unique_molecules = true" in text
    assert "randomize_smiles = false" in text
    assert "smiles_file" not in text
    assert "sample_strategy" not in text
    assert "temperature" not in text


def test_seed_generators_write_their_extra_fields(tmp_path: Path) -> None:
    lib = render_sampling_toml(
        _request(generator="libinvent", sample_strategy="multinomial", seeds=("*C",)),
        output_file=tmp_path / "out.csv",
        smiles_file=tmp_path / "seeds.smi",
    )
    assert 'sample_strategy = "multinomial"' in lib
    assert "smiles_file" in lib
    assert "temperature" not in lib

    mol2mol = render_sampling_toml(
        _request(
            generator="mol2mol",
            model_file=".m2m_similarity",
            sample_strategy="beamsearch",
            temperature=0.7,
            seeds=("CCO",),
        ),
        output_file=tmp_path / "out.csv",
        smiles_file=tmp_path / "seeds.smi",
    )
    assert "temperature = 0.7" in mol2mol
    assert 'sample_strategy = "beamsearch"' in mol2mol


def test_toml_quotes_a_model_path(tmp_path: Path) -> None:
    model = tmp_path / 'my "prior".prior'
    text = render_sampling_toml(
        _request(model_file=str(model)),
        output_file=tmp_path / "sampling.csv",
        smiles_file=None,
    )
    assert model.as_posix().replace('"', '\\"') in text


def test_write_inputs_uses_posix_seed_file(tmp_path: Path) -> None:
    config, output = write_sampling_inputs(
        tmp_path,
        _request(generator="mol2mol", sample_strategy="multinomial", seeds=("CCO", "c1ccccc1")),
    )
    body = config.read_text(encoding="utf-8")
    assert output.name == "sampling.csv"
    assert (tmp_path / "seeds.smi").read_text(encoding="utf-8") == "CCO\nc1ccccc1\n"
    assert "\\" not in body


def test_parse_sampling_csv_keeps_nll_and_seed(tmp_path: Path) -> None:
    path = tmp_path / "sampling.csv"
    path.write_text(
        "SMILES,NLL,Input_SMILES\nCCO,1.25,CC\nnot-a-header,2,CC\n",
        encoding="utf-8",
    )
    rows = parse_sampling_csv(path)
    assert [(row.smiles, row.nll, row.seed_smiles) for row in rows] == [
        ("CCO", "1.25", "CC"),
        ("not-a-header", "2", "CC"),
    ]


def test_parse_sampling_csv_without_a_header(tmp_path: Path) -> None:
    path = tmp_path / "sampling.csv"
    path.write_text("CCO,3.5\n", encoding="utf-8")
    rows = parse_sampling_csv(path)
    assert rows[0].smiles == "CCO"
    assert rows[0].nll == "3.5"


def test_outcome_drops_unreadable_smiles(tmp_path: Path) -> None:
    path = tmp_path / "sampling.csv"
    path.write_text("SMILES,NLL\nCCO,1\nnot_smiles,2\n", encoding="utf-8")
    outcome = outcome_from_csv(path, _request(model_file=".reinvent"), cancelled=False)
    assert outcome.parsed == 2
    assert outcome.skipped_invalid == 1
    assert outcome.records[0][0] == "CCO"
    assert outcome.records[0][1]["REINVENT_Generator"] == "De novo"
    assert outcome.records[0][1]["REINVENT_Model"] == ".reinvent"
    assert outcome.records[0][1]["REINVENT_NLL"] == "1"


def test_seed_rules() -> None:
    assert normalize_seed_lines(" \n# note\nCCO\n") == ("CCO",)
    assert validate_seeds("denovo", ()) is None
    assert validate_seeds("libinvent", ("CCO",)) is not None
    assert validate_seeds("libinvent", ("*c1ccccc1",)) is None
    assert validate_seeds("linkinvent", ("*c1ccccc1",)) is not None
    assert validate_seeds("linkinvent", ("*c1ccccc1|*c1ccncc1",)) is None
    assert validate_seeds("mol2mol", ("CCO",)) is None
    assert validate_request(_request(model_file="")) is not None
    assert seed_text_for_row("*C|*N", None) == "*C|*N"
    assert seed_text_for_row("CCO", None) == "CCO"


def test_execute_sampling_reads_the_csv(tmp_path: Path) -> None:
    body = """
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[-1]).read_text(encoding="utf-8")
match = re.search(r'output_file = "([^"]+)"', text)
pathlib.Path(match.group(1)).write_text(
    "SMILES,NLL\\nCCO,4.0\\n",
    encoding="utf-8",
)
print("sampled", flush=True)
"""
    executable = _fake_reinvent(tmp_path, body)
    logs: list[str] = []
    outcome = execute_sampling(
        str(executable),
        _request(num_smiles=2),
        on_log=logs.append,
        work_dir=tmp_path / "work",
    )
    assert outcome.records[0][0] == "CCO"
    assert any("sampled" in line for line in logs)
    assert (tmp_path / "work" / "sampling.toml").is_file()


def test_execute_sampling_can_be_stopped(tmp_path: Path) -> None:
    body = """
import time

print("start", flush=True)
time.sleep(30)
"""
    executable = _fake_reinvent(tmp_path, body)
    seen: list[str] = []

    def cancel() -> bool:
        return bool(seen)

    def on_log(line: str) -> None:
        seen.append(line)

    outcome = execute_sampling(
        str(executable),
        _request(),
        cancel=cancel,
        on_log=on_log,
        work_dir=tmp_path / "work",
    )
    assert outcome.cancelled is True
    assert outcome.records == ()


def test_describe_reinvent_accepts_a_version_line(tmp_path: Path) -> None:
    executable = _fake_reinvent(tmp_path, "import sys\nprint('REINVENT 4.6.15')\n")
    ok, message = describe_reinvent(str(executable))
    assert ok is True
    assert "REINVENT 4.6.15" in message


def test_describe_reinvent_refuses_this_interpreter() -> None:
    ok, message = describe_reinvent(sys.executable)
    assert ok is False
    assert "own environment" in message


def test_missing_reinvent_message(tmp_path: Path) -> None:
    ok, message = describe_reinvent(str(tmp_path / "missing-reinvent.exe"))
    assert ok is False
    assert "not found" in message.lower()


def test_configure_dialog_opens(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.tool_path_settings import ToolPathDialog

    dialog = ToolPathDialog("reinvent")
    assert dialog.windowTitle() == "REINVENT"
    dialog.close()


def test_dialog_switches_model_with_the_generator(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.reinvent_sampling import ReinventSamplingDialog

    dialog = ReinventSamplingDialog(None)
    assert dialog.request().generator == "denovo"
    assert dialog.request().model_file == ".reinvent"
    assert dialog.seed_box.isHidden()
    dialog.generator_combo.setCurrentIndex(1)
    request = dialog.request()
    assert request.generator == "libinvent"
    assert request.model_file == ".libinvent"
    assert request.sample_strategy == "multinomial"
    assert not dialog.seed_box.isHidden()
    dialog.model_edit.setText(r"C:\models\custom.prior")
    dialog.generator_combo.setCurrentIndex(3)
    assert dialog.model_edit.text().endswith("custom.prior")
    assert dialog.request().generator == "mol2mol"
    assert not dialog.temperature_spin.isHidden()
    dialog.close()


def test_scaffold_keeps_matches_and_can_seed_libinvent(tmp_path: Path) -> None:
    path = tmp_path / "sampling.csv"
    path.write_text("SMILES,NLL\nc1ccccc1,1.0\nCCO,2.0\n", encoding="utf-8")
    outcome = outcome_from_csv(
        path,
        _request(scaffold_smarts="c1ccccc1"),
        cancelled=False,
    )
    assert [smiles for smiles, _fields in outcome.records] == ["c1ccccc1"]
    assert outcome.skipped_scaffold == 1
    assert validate_request(_request(scaffold_smarts="not smarts [")) is not None
    seeded = validate_request(
        _request(
            generator="libinvent",
            model_file=".libinvent",
            sample_strategy="multinomial",
            scaffold_smarts="*c1ccccc1",
        )
    )
    assert seeded is None
    _config, _csv = write_sampling_inputs(
        tmp_path / "job",
        _request(
            generator="libinvent",
            model_file=".libinvent",
            sample_strategy="multinomial",
            scaffold_smarts="*c1ccccc1",
        ),
    )
    assert "*c1ccccc1" in (tmp_path / "job" / "seeds.smi").read_text(encoding="utf-8")


def test_dialog_has_a_scaffold_field(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.reinvent_sampling import ReinventSamplingDialog

    dialog = ReinventSamplingDialog(None)
    dialog.scaffold_edit.setText("c1ccccc1")
    assert dialog.request().scaffold_smarts == "c1ccccc1"
    assert dialog.request().seed == 0
    assert dialog.request().extra_flags == ""
    assert dialog.scaffold_sketch.text() == "Sketcher…"
    dialog.seed_spin.setValue(9)
    dialog.isomeric_check.setChecked(True)
    dialog.extra_flags_edit.setText("--log-level debug")
    request = dialog.request()
    assert request.seed == 9
    assert request.isomeric_smiles is True
    assert request.extra_flags == "--log-level debug"
    dialog.close()


@pytest.mark.parametrize(
    ("generator", "strategy"),
    [("denovo", ""), ("libinvent", "multinomial")],
)
def test_validate_request_accepts_a_ready_job(generator: str, strategy: str) -> None:
    seeds = ("*c1ccccc1",) if generator == "libinvent" else ()
    assert (
        validate_request(_request(generator=generator, sample_strategy=strategy, seeds=seeds))
        is None
    )


def test_optional_sampling_fields_and_extra_flags(tmp_path: Path) -> None:
    text = render_sampling_toml(
        _request(seed=3, isomeric_smiles=True),
        output_file=tmp_path / "sampling.csv",
        smiles_file=None,
    )
    assert "seed = 3" in text
    assert "isomeric_smiles = true" in text
    flags = parse_extra_flags('--seed 7 --log-filename "C:\\temp\\reinvent.log"')
    assert flags == ("--seed", "7", "--log-filename", "C:\\temp\\reinvent.log")
    assert parse_extra_flags("") == ()
    assert validate_request(_request(extra_flags="--not-a-flag")) is not None
    assert validate_request(_request(extra_flags="--seed")) is not None
    assert validate_request(_request(seed=-1)) is not None


def test_extra_flags_reach_the_command(tmp_path: Path) -> None:
    argv_path = tmp_path / "argv.txt"
    body = f"""
import pathlib
import re
import sys

pathlib.Path({str(argv_path)!r}).write_text("\\n".join(sys.argv), encoding="utf-8")
text = pathlib.Path(sys.argv[-1]).read_text(encoding="utf-8")
match = re.search(r'output_file = "([^"]+)"', text)
pathlib.Path(match.group(1)).write_text("SMILES,NLL\\nCCO,1.0\\n", encoding="utf-8")
"""
    outcome = execute_sampling(
        str(_fake_reinvent(tmp_path, body)),
        _request(extra_flags="--log-level debug"),
        work_dir=tmp_path / "work",
    )
    argv = argv_path.read_text(encoding="utf-8").splitlines()
    assert outcome.records[0][0] == "CCO"
    assert "--log-level" in argv
    assert "debug" in argv
    assert argv[-1].endswith("sampling.toml")


def test_reinvent_browser_lists_rows_and_adds_them(qapp) -> None:  # noqa: ARG001
    from molmanager.generative.reinvent_results import results_status
    from molmanager.ui.browsers.reinvent_browser import (
        ReinventBrowserWidget,
        add_reinvent_records_to_table,
    )

    widget = ReinventBrowserWidget(None)
    widget.set_records([("CCO", {"REINVENT_NLL": "1.5"})], title="REINVENT Sampling")
    assert widget._window_title == "REINVENT Sampling Browser"
    assert widget._table.rowCount() == 1
    assert widget._table.item(0, 1).text() == "CCO"
    assert widget._table.item(0, 2).text() == "1.5"
    widget.close()

    class _App:
        def __init__(self) -> None:
            self.rows: list = []

        def existing_canonical_structure_keys(self) -> set[str]:
            return set()

        def canonical_structure_key_from_smiles(self, smiles: str) -> str:
            return smiles

        def add_rows_from_external_records_batch(self, batch, render_structures=True) -> int:
            self.rows.extend(batch)
            return len(batch)

    app = _App()
    added, skipped = add_reinvent_records_to_table(
        app,
        (("CCO", {"REINVENT_NLL": "1.5"}), ("CCO", {"REINVENT_NLL": "2"})),
        unique_only=True,
    )
    assert (added, skipped) == (1, 1)
    assert app.rows[0][0] == "CCO"
    assert results_status(count=1, cancelled=False, skipped="") == (
        "Opened 1 molecule in the REINVENT browser."
    )
