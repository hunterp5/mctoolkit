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

"""Recordable commands. Plain data: no Qt, no window, no execution.

The recipe steps are the first entries. A later recorder appends the same
step kinds the macro editor already writes. Output keys for a specific step
still come from ``macro_recipe.output_keys``, because descriptor keys depend
on which descriptors that step asked for.
"""

from __future__ import annotations

from dataclasses import dataclass

from .macro_recipe import (
    STEP_CALCULATOR,
    STEP_DESCRIPTORS,
    STEP_EXPLICIT_H,
    STEP_EXTRACT,
    STEP_FAST_PREPARE,
    STEP_FILTER,
    STEP_NEUTRALIZE,
    STEP_PLOT,
    STEP_POTENCY,
    STEP_PROTONATE,
    STEP_RANDOM,
    STEP_REACTION,
    STEP_REMOVE_H,
    STEP_RGROUP,
    STEP_SIMULATION,
)

COMPLETION_PROCESS_QUEUE = "process_queue"
COMPLETION_BACKGROUND = "background"
COMPLETION_WRITEBACK = "writeback"
COMPLETION_SYNC = "sync"

# Stable ids. Menus and the recorder use these, not widget method names.
COMMAND_DESCRIPTORS = "chemistry.descriptors"
COMMAND_CALCULATOR = "tools.calculator"
COMMAND_PROTONATE = "chemistry.protonate"
COMMAND_FILTER = "table.filter.apply"
COMMAND_REACTION = "chemistry.reaction_enumeration"
COMMAND_RANDOM = "tools.random_number"
COMMAND_EXTRACT = "chemistry.reaction_extract"
COMMAND_PLOT = "view.plot.apply"
COMMAND_POTENCY = "tools.potency"
COMMAND_RGROUP = "chemistry.rgroup_enumeration"
COMMAND_EXPLICIT_H = "chemistry.explicit_hydrogens.add"
COMMAND_REMOVE_H = "chemistry.explicit_hydrogens.remove"
COMMAND_NEUTRALIZE = "chemistry.neutralize"
COMMAND_FAST_PREPARE = "chemistry.fast_prepare"
COMMAND_SIMULATION = "protein.simulation"


@dataclass(frozen=True)
class CommandSpec:
    """One command the recorder will be able to append and the runner can play."""

    command_id: str
    step_kind: str
    label: str
    menu: str
    completion: str


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        COMMAND_DESCRIPTORS,
        STEP_DESCRIPTORS,
        "Calculate descriptors",
        "Chemistry → Calculate Descriptors",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_CALCULATOR,
        STEP_CALCULATOR,
        "Calculator",
        "Tools → Calculator",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_PROTONATE,
        STEP_PROTONATE,
        "Protonate",
        "Chemistry → Prepare Structures → Protonate",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_FILTER,
        STEP_FILTER,
        "Filter",
        "Data → Filters",
        COMPLETION_BACKGROUND,
    ),
    CommandSpec(
        COMMAND_REACTION,
        STEP_REACTION,
        "Reaction enumeration",
        "Chemistry → Structure Enumeration → Reaction Based",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_RANDOM,
        STEP_RANDOM,
        "Random number",
        "Tools → Random → Number",
        COMPLETION_WRITEBACK,
    ),
    CommandSpec(
        COMMAND_EXTRACT,
        STEP_EXTRACT,
        "Extract reaction",
        "Chemistry → Extract Reaction Info",
        COMPLETION_WRITEBACK,
    ),
    CommandSpec(
        COMMAND_PLOT,
        STEP_PLOT,
        "Plot",
        "Tools → Macros → Add plot",
        COMPLETION_SYNC,
    ),
    CommandSpec(
        COMMAND_POTENCY,
        STEP_POTENCY,
        "Potency",
        "Tools → Potency Standardization",
        COMPLETION_WRITEBACK,
    ),
    CommandSpec(
        COMMAND_RGROUP,
        STEP_RGROUP,
        "R-group enumeration",
        "Chemistry → Structure Enumeration → R-Group",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_EXPLICIT_H,
        STEP_EXPLICIT_H,
        "Add explicit hydrogens",
        "Chemistry → Prepare Structures → Explicit Hydrogens → Add",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_REMOVE_H,
        STEP_REMOVE_H,
        "Remove explicit hydrogens",
        "Chemistry → Prepare Structures → Explicit Hydrogens → Remove",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_NEUTRALIZE,
        STEP_NEUTRALIZE,
        "Neutralize",
        "Chemistry → Prepare Structures → Protonate → Neutralize",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_FAST_PREPARE,
        STEP_FAST_PREPARE,
        "Fast prepare",
        "Chemistry → Prepare Structures → Fast Prepare",
        COMPLETION_PROCESS_QUEUE,
    ),
    CommandSpec(
        COMMAND_SIMULATION,
        STEP_SIMULATION,
        "Simulation",
        "Protein → Simulation",
        COMPLETION_PROCESS_QUEUE,
    ),
)

_BY_KIND = {spec.step_kind: spec for spec in COMMANDS}
_BY_ID = {spec.command_id: spec for spec in COMMANDS}


def command_for_step_kind(kind: str) -> CommandSpec | None:
    """The catalog entry for a recipe step kind, or None when it is not recordable yet."""
    return _BY_KIND.get(kind)


def command_by_id(command_id: str) -> CommandSpec | None:
    """The catalog entry for a stable command id."""
    return _BY_ID.get(command_id)
