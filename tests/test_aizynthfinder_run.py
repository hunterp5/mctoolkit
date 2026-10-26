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

"""AiZynthFinder config checks, checkpoint parsing, and the local process wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import molmanager.predictions.aizynthfinder_run as aizynth
from molmanager.platform_support.tool_paths import (
    TOOL_AIZYNTH_CONFIG,
    TOOL_AIZYNTH_PYTHON,
    save_tool_path,
)


_LOCAL_CONFIG = """
expansion:
  uspto:
    - uspto_model.onnx
    - uspto_templates.csv.gz
stock:
  zinc: zinc_stock.hdf5
"""


def test_remote_policy_and_remote_stock_are_refused() -> None:
    remote_model = _LOCAL_CONFIG + "\nexpansion_policy:\n  use_remote_models: true\n"
    assert "server" in (aizynth.config_text_problem(remote_model) or "")
    remote_stock = "stock:\n  type: mongodb\n  host: stock.example.com\n  expansion: []\n"
    assert "MongoDB" in (aizynth.config_text_problem(remote_stock) or "")
    local_mongo = "stock:\n  type: mongodb\n  host: localhost\nexpansion:\n  uspto: model.onnx\n"
    assert aizynth.config_text_problem(local_mongo) is None
    assert aizynth.config_text_problem(_LOCAL_CONFIG) is None


def test_ready_message_rejects_this_interpreter(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text(_LOCAL_CONFIG, encoding="utf-8")
    message = aizynth.ready_message(aizynth.sys.executable, str(config))
    assert message is not None
    assert "own environment" in message


def test_saved_paths_roundtrip_into_ready_message(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text(_LOCAL_CONFIG, encoding="utf-8")
    save_tool_path(TOOL_AIZYNTH_PYTHON, str(python))
    save_tool_path(TOOL_AIZYNTH_CONFIG, str(config))
    assert aizynth.ready_message() is None
    assert aizynth.resolve_python() == str(python)
    assert aizynth.resolve_config() == config


def test_checkpoint_and_output_table_become_columns(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps(
            {
                "processed_smiles": "CCO",
                "results": {
                    "is_solved": True,
                    "number_of_solved_routes": 2,
                    "top_score": 0.9876,
                    "number_of_steps": 3,
                    "search_time": 12.34,
                    "precursors_in_stock": "CCO, CC",
                    "precursors_not_in_stock": "",
                    "trees": [{"huge": True}],
                },
            }
        )
        + "\nnot-json\n",
        encoding="utf-8",
    )
    columns = aizynth.summaries_from_checkpoint(checkpoint)["CCO"]
    assert columns[aizynth.COLUMN_SOLVED] == "yes"
    assert columns[aizynth.COLUMN_SOLVED_ROUTES] == "2"
    assert columns[aizynth.COLUMN_SCORE] == "0.988"
    assert columns[aizynth.COLUMN_STEPS] == "3"
    assert columns[aizynth.COLUMN_TIME] == "12.3"
    assert columns[aizynth.COLUMN_IN_STOCK] == "CCO, CC"
    assert "trees" not in columns

    output = tmp_path / "output.json.gz"
    payload = {
        "schema": {"fields": []},
        "data": [
            {
                "target": "CCN",
                "is_solved": False,
                "number_of_solved_routes": 0,
                "top_score": 0.1,
                "number_of_steps": 1,
                "search_time": 2,
                "precursors_in_stock": ["CC"],
                "precursors_not_in_stock": ["N"],
            }
        ],
    }
    import gzip

    with gzip.open(output, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    parsed = aizynth.summaries_from_output(output)["CCN"]
    assert parsed[aizynth.COLUMN_SOLVED] == "no"
    assert parsed[aizynth.COLUMN_IN_STOCK] == "CC"
    assert parsed[aizynth.COLUMN_NOT_IN_STOCK] == "N"


def test_conda_child_environment_prefixes_library_bin(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "env"
    lib = root / "Library" / "bin"
    lib.mkdir(parents=True)
    (root / "conda-meta").mkdir()
    python = root / "python.exe"
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", r"C:\molmanager")
    monkeypatch.setenv("CONDA_PREFIX", r"C:\Users\hunte\miniconda3")
    monkeypatch.setenv("PATH", r"C:\Windows")
    env = aizynth.child_environment(python)
    assert "PYTHONPATH" not in env
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["CONDA_PREFIX"] == str(root)
    assert env["PATH"].startswith(str(root))
    assert str(lib) in env["PATH"]


def test_run_search_reads_checkpoint_and_kills_on_cancel(tmp_path: Path, monkeypatch) -> None:
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text(_LOCAL_CONFIG, encoding="utf-8")
    seen: dict[str, object] = {}

    class _Proc:
        def __init__(self, args, **kwargs):
            seen["args"] = list(args)
            seen["cwd"] = kwargs.get("cwd")
            seen["env"] = kwargs.get("env")
            checkpoint = Path(args[args.index("--checkpoint") + 1])
            checkpoint.write_text(
                json.dumps(
                    {
                        "processed_smiles": "CCO",
                        "results": {"is_solved": True, "number_of_solved_routes": 1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.returncode = None
            self.stdout = None
            self.stderr = None
            self._polls = 0

        def poll(self):
            self._polls += 1
            if self._polls > 1:
                self.returncode = 0
            return self.returncode

        def kill(self):
            self.returncode = 1

        def wait(self, timeout=None):  # noqa: ARG002
            self.returncode = 0
            return 0

    monkeypatch.setattr(aizynth.subprocess, "Popen", _Proc)
    monkeypatch.setattr(aizynth.time, "sleep", lambda _seconds: None)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    result = aizynth.run_search(python=str(python), config=config, smiles=["CCO"])
    assert result.summaries["CCO"][aizynth.COLUMN_SOLVED] == "yes"
    command = seen["args"]
    assert isinstance(command, list)
    assert command[0] == str(python)
    assert "--nproc" not in command
    assert seen["cwd"] == str(config.parent)
    env = seen["env"]
    assert isinstance(env, dict)
    assert "PYTHONPATH" not in env

    kept = aizynth.run_search(
        python=str(python),
        config=config,
        smiles=["CCO"],
        cancel=lambda: True,
    )
    assert kept.cancelled
    assert kept.summaries["CCO"][aizynth.COLUMN_SOLVED] == "yes"

    class _Silent:
        def __init__(self, args, **kwargs):
            self.returncode = None
            self.stdout = None
            self.stderr = None

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = 1

        def wait(self, timeout=None):  # noqa: ARG002
            return self.returncode

    monkeypatch.setattr(aizynth.subprocess, "Popen", _Silent)
    try:
        aizynth.run_search(
            python=str(python),
            config=config,
            smiles=["CCO"],
            cancel=lambda: True,
        )
    except aizynth.AizynthRunError as exc:
        assert str(exc) == "Cancelled."
    else:
        raise AssertionError("cancel before a checkpoint should fail the search")
