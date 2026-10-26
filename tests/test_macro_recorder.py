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

"""Recording appends a finished job and rewrites the header it wrote."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.ui.job_handle import JobHandle
from molmanager.ui.macro_recorder import MacroRecorder
from molmanager.workflows.macro_recipe import (
    STEP_CALCULATOR,
    STEP_DESCRIPTORS,
    STEP_EXTRACT,
    MacroStep,
)
from molmanager.workflows.macro_record import (
    calculator_step,
    descriptor_step,
    extract_step,
    rewrite_recorded_text,
)
from molmanager.workflows.tool_requests import (
    CalculatorColumnRequest,
    DescriptorCalculationRequest,
    row_scope_from_only_selected,
)


def test_rewrite_replaces_the_written_header_inside_brackets():
    text = rewrite_recorded_text(
        "[Mol Weight] / 2",
        {"desc1": {"MolWt": "Mol Weight", "MolLogP": "LogP"}},
    )
    assert text == "[${desc1.MolWt}] / 2"


def test_recording_appends_on_success_and_rewrites_the_next_expression(qapp):
    recorder = MacroRecorder()
    recorder.start()
    descriptor = descriptor_step(
        DescriptorCalculationRequest(
            structure_source="Structure",
            keys=("MolWt", "MolLogP"),
            row_scope=row_scope_from_only_selected(False),
        )
    )
    first = JobHandle("chemistry.descriptors")
    recorder.observe(descriptor, first)
    assert recorder.steps == []
    first.succeed({"MolWt": "Mol Weight", "MolLogP": "LogP"})
    qapp.processEvents()
    assert [step.kind for step in recorder.steps] == [STEP_DESCRIPTORS]
    assert recorder.steps[0].id == "desc1"
    assert recorder.steps[0].params["descriptors"] == ["MolWt", "MolLogP"]

    calculator = calculator_step(
        CalculatorColumnRequest(column="Calc", expression="[Mol Weight] / 2", row_scope="table")
    )
    second = JobHandle("tools.calculator")
    recorder.observe(calculator, second)
    second.succeed({"output": "Calc"})
    qapp.processEvents()
    assert [step.kind for step in recorder.steps] == [STEP_DESCRIPTORS, STEP_CALCULATOR]
    assert recorder.steps[1].params["expression"] == "[${desc1.MolWt}] / 2"


def test_extract_recording_publishes_columns_in_write_order(qapp):
    recorder = MacroRecorder()
    recorder.start()

    class _Request:
        source_column = "Mol Weight"
        mode = "reactants"
        reactant_prefix = "Reactant"
        product_prefix = "Product"

    step = extract_step(_Request(), "table")
    handle = JobHandle("chemistry.reaction_extract")
    recorder.observe(step, handle)
    handle.succeed({"col_1": "Reactant 1", "col_2": "Reactant 2"})
    qapp.processEvents()
    assert recorder.steps[0].kind == STEP_EXTRACT
    assert recorder.steps[0].params["source_column"] == "Mol Weight"
    assert recorder.steps[0].params["published"] == ["col_1", "col_2"]

    recorder2 = MacroRecorder()
    recorder2.start()
    first = JobHandle("chemistry.descriptors")
    recorder2.observe(
        MacroStep(
            id="pending",
            kind=STEP_DESCRIPTORS,
            params={"descriptors": ["MolWt"], "structure_source": "Structure"},
        ),
        first,
    )
    first.succeed({"MolWt": "Mol Weight"})
    qapp.processEvents()
    recorded = extract_step(_Request(), "table")
    second = JobHandle("chemistry.reaction_extract")
    recorder2.observe(recorded, second)
    second.succeed({"col_1": "Reactant 1"})
    qapp.processEvents()
    assert recorder2.steps[1].params["source_column"] == "${desc1.MolWt}"
    assert recorder2.steps[1].params["published"] == ["col_1"]


def test_cancelled_and_replay_do_not_append(qapp):
    recorder = MacroRecorder()
    recorder.start()
    cancelled = JobHandle("chemistry.descriptors")
    recorder.observe(
        MacroStep(id="pending", kind=STEP_DESCRIPTORS, params={"descriptors": ["MolWt"]}),
        cancelled,
    )
    cancelled.fail("Cancelled.", cancelled=True)
    qapp.processEvents()
    assert recorder.steps == []

    recorder.begin_replay()
    replayed = JobHandle("chemistry.descriptors")
    recorder.observe(
        MacroStep(id="pending", kind=STEP_DESCRIPTORS, params={"descriptors": ["MolWt"]}),
        replayed,
    )
    replayed.succeed({"MolWt": "Mol Weight"})
    qapp.processEvents()
    assert recorder.steps == []
    recorder.end_replay()
