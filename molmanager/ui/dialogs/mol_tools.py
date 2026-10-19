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

"""Compatibility re-exports for molecule-tool dialogs.

Prefer importing from the dedicated dialog modules. This module remains
stable for existing imports.
"""

from __future__ import annotations

from .conformer_output import (
    ConformerOutputOptions,
    ConformerOutputOptionsPanel,
    conformer_options_group,
)
from .disconnect_fragments import DisconnectFragmentsDialog
from .explicit_hydrogens import AddExplicitHydrogensDialog, RemoveExplicitHydrogensDialog
from .fast_prepare import FastPrepareDialog
from .fragment_decomposition import (
    CoreBasedDecompDialogParams,
    CoreBasedDecompositionDialog,
    FragmentDecompDialogParams,
    FragmentDecompositionDialog,
    FragmentRecompDialogParams,
    FragmentRecompositionDialog,
)
from .generate_conformations import GenerateConformationsDialog
from .neutralize import NeutralizeDialog
from .superpose import SuperposeConformersDialog, SuperposeDialog, SuperposeStructuresDialog

__all__ = [
    "AddExplicitHydrogensDialog",
    "ConformerOutputOptions",
    "ConformerOutputOptionsPanel",
    "CoreBasedDecompDialogParams",
    "CoreBasedDecompositionDialog",
    "DisconnectFragmentsDialog",
    "FastPrepareDialog",
    "FragmentDecompDialogParams",
    "FragmentDecompositionDialog",
    "FragmentRecompDialogParams",
    "FragmentRecompositionDialog",
    "GenerateConformationsDialog",
    "NeutralizeDialog",
    "RemoveExplicitHydrogensDialog",
    "SuperposeConformersDialog",
    "SuperposeDialog",
    "SuperposeStructuresDialog",
    "conformer_options_group",
]
