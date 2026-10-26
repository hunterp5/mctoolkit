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
    STEP_FILTER,
    STEP_PROTONATE,
    STEP_REACTION,
)

COMPLETION_PROCESS_QUEUE = "process_queue"
COMPLETION_BACKGROUND = "background"

# Stable ids. Menus and the recorder use these, not widget method names.
COMMAND_DESCRIPTORS = "chemistry.descriptors"
COMMAND_CALCULATOR = "tools.calculator"
COMMAND_PROTONATE = "chemistry.protonate"
COMMAND_FILTER = "table.filter.apply"
COMMAND_REACTION = "chemistry.reaction_enumeration"


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
)

_BY_KIND = {spec.step_kind: spec for spec in COMMANDS}
_BY_ID = {spec.command_id: spec for spec in COMMANDS}


def command_for_step_kind(kind: str) -> CommandSpec | None:
    """The catalog entry for a recipe step kind, or None when it is not recordable yet."""
    return _BY_KIND.get(kind)


def command_by_id(command_id: str) -> CommandSpec | None:
    """The catalog entry for a stable command id."""
    return _BY_ID.get(command_id)
