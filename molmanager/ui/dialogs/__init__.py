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

"""Modal and modeless tool dialogs (split into submodules for maintainability).

Exports are loaded lazily so importing a submodule (e.g. ``protein_prepare``)
does not pull Qt WebEngine via ``PlotDialog``.
"""

from __future__ import annotations

import importlib
from typing import Any

# Relative to this package. ``..plot`` / ``..sketcher`` stay out of package init.
_EXPORTS: dict[str, str] = {
    "AlignSubstructureDialog": ".align_substructure",
    "AlignSubstructureConfig": ".align_substructure",
    "ActivityCliffDialog": ".activity_cliff",
    "ActivityCliffDialogParams": ".activity_cliff",
    "AddExplicitHydrogensDialog": ".explicit_hydrogens",
    "BemisMurckoDialog": ".substructure",
    "BiotransformerDialog": ".biotransformer",
    "BulkSimilarityDialog": ".bulk_similarity",
    "CalculatorDialog": ".calculator",
    "ClusterDialog": ".cluster",
    "CommonCoreDialog": ".substructure",
    "CommonCoreDialogParams": ".substructure",
    "ConforgeConformationsDialog": ".conforge_conformations",
    "CoreBasedDecompDialogParams": ".fragment_decomposition",
    "CoreBasedDecompositionDialog": ".fragment_decomposition",
    "DataAnalysisDialog": ".data_analysis",
    "DisconnectFragmentsDialog": ".disconnect_fragments",
    "DiverseSubsetDialog": ".diverse_subset",
    "FPSimilarityDialog": ".fp_similarity",
    "FastPrepareDialog": ".fast_prepare",
    "FreeWilsonDialog": ".free_wilson",
    "FreeWilsonDialogParams": ".free_wilson",
    "FreeWilsonResultsDialog": ".free_wilson_results",
    "FragmentDecompDialogParams": ".fragment_decomposition",
    "FragmentDecompositionDialog": ".fragment_decomposition",
    "FragmentRecompDialogParams": ".fragment_decomposition",
    "FragmentRecompositionDialog": ".fragment_decomposition",
    "GenerateConformationsDialog": ".generate_conformations",
    "MPOScoringDialog": ".mpo_scoring",
    "MPOScoringDialogParams": ".mpo_scoring",
    "MmpDialog": ".mmp",
    "MmpDialogParams": ".mmp",
    "MmpNeighborhoodDialog": ".mmp_neighborhood",
    "MmpNeighborhoodDialogParams": ".mmp_neighborhood",
    "NeutralizeDialog": ".neutralize",
    "PKaPredictorDialog": ".pka",
    "PdbqtGeneratorDialog": ".pdbqt_generator",
    "PharmacophoreScreenDialog": ".pharmacophore_screen",
    "PermeabilityPredictorDialog": ".permeability",
    "PotencyStandardizationDialog": ".potency",
    "PlotDialog": "..plot",
    "PropertyDialog": ".properties",
    "ProteinPrepareDialog": ".protein_prepare",
    "ProteinDockFileDialog": ".protein_dock_file",
    "ProteinMinimizeDialog": ".protein_minimize",
    "ProteinPdbFixerDialog": ".protein_pdbfixer",
    "ProteinPdb2pqrDialog": ".protein_pdb2pqr",
    "ProteinPocketSurfaceDialog": ".protein_pocket_surface",
    "ProteinPharmacophoreDialog": ".protein_pharmacophore",
    "ProteinSequenceMsaDialog": ".protein_sequence_msa",
    "ProtomerGeneratorDialog": ".protomer",
    "ProtonateDialog": ".protonate",
    "AutoQSARDialog": ".auto_qsar",
    "ComsiaDialog": ".comsia",
    "QSARDialog": ".qsar",
    "RandomMoleculeDialog": ".random_molecule",
    "RandomMoleculeDialogParams": ".random_molecule",
    "RandomNumberDialog": ".random_number",
    "RandomNumberDialogParams": ".random_number",
    "ReactionEnumerationDialog": ".reaction_enumeration",
    "RGroupEnumerationDialog": ".rgroup_enumeration",
    "ReactionExtractDialog": ".reaction_extract",
    "ReactionExtractDialogParams": ".reaction_extract",
    "RemoveExplicitHydrogensDialog": ".explicit_hydrogens",
    "Render2DStructureDialog": ".render_2d",
    "SarMatrixDialog": ".sar_matrix",
    "SarMatrixDialogParams": ".sar_matrix",
    "InteractionFingerprintDialog": ".interaction_fingerprint",
    "InteractionFingerprintDialogParams": ".interaction_fingerprint",
    "SaliDialog": ".sali",
    "SaliDialogParams": ".sali",
    "SketchWidget": "..sketcher",
    "SketcherDialog": "..sketcher",
    "GninaDockDialog": ".gnina_dock",
    "SminaDockDialog": ".smina_dock",
    "SplitColumnDialog": ".split_column",
    "SplitColumnDialogParams": ".split_column",
    "JoinColumnsDialog": ".join_columns",
    "JoinColumnsDialogParams": ".join_columns",
    "BinningDialog": ".binning",
    "BinningDialogParams": ".binning",
    "SuperposeConformersDialog": ".superpose",
    "SuperposeDialog": ".superpose",
    "SuperposeStructuresDialog": ".superpose",
    "SystematicConformationsDialog": ".systematic_conformations",
    "selection_scope_checked": ".scope",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(mod_name, __package__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
