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
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Background workers (load, render, chemistry tools, export)."""

from __future__ import annotations

import importlib
from typing import Any

# Exports resolve on first attribute access so importing the package (or one light submodule)
# does not load every worker's chemistry stack at application start.
_LAZY_EXPORT_MODULES: dict[str, tuple[str, ...]] = {
    ".chemistry_tools": (
        "CalcWorker",
        "ConformerGenParams",
        "ConformerGenerationWorker",
        "CustomCalcWorker",
        "describe_custom_calc_error",
        "format_confs_table_cell",
        "pack_confs_cell",
        "run_conformer_generation",
        "SuperposeConformersWorker",
        "SuperposeStructuresWorker",
        "SuperposeParams",
        "SuperposeStructuresParams",
        "RmsdParams",
        "StrainEnergyParams",
        "StrainEnergyWorker",
        "STRAIN_ENERGY_HEADERS",
        "run_superpose_conformers",
        "run_superpose_structures",
        "align_structure_onto_reference",
        "run_conformer_rmsd",
        "run_strain_energy",
        "strain_overlay_for_mol",
        "strain_overlay_for_mols",
        "strain_overlay_for_blocks_b64",
    ),
    ".chemistry_descriptors": ("CalcDescriptorsRequest",),
    ".bulk_similarity": ("BulkSimilarityResult", "BulkSimilarityWorker"),
    ".cluster_worker": ("ClusterExploreWorker", "ClusterWorker"),
    ".common_core": ("CommonCoreWorker",),
    ".export_worker": ("ExportWorker",),
    "..chem.rdkit_fingerprints": (
        "SIMILARITY_FP_TYPE_LABELS",
        "fingerprint_bitvect_for_ui_choice",
    ),
    ".diverse_subset_worker": (
        "DiverseSubsetWorker",
        "build_diverse_subset_pool",
        "materialize_pool_fingerprints",
        "maxmin_diverse_pick_bulk",
        "maxmin_diverse_pick_indices",
        "maxmin_diverse_pick_lazy",
        "run_diverse_subset_pick",
    ),
    ".fingerprint_similarity": (
        "FPSimilarityWorker",
        "SIMILARITY_METRIC_LABELS",
        "pairwise_fingerprint_similarity",
    ),
    ".pharmacophore_screen": ("PharmacophoreScreenWorker",),
    ".fast_prepare": ("FastPrepareWorker",),
    ".load_render": (
        "AddExplicitHydrogensWorker",
        "NeutralizeWorker",
        "RemoveExplicitHydrogensWorker",
        "Render2DBatchHeldJob",
        "Render2DBatchProcessWorker",
        "RenderWorker",
        "UniversalLoadWorker",
        "DisconnectFragmentsWorker",
    ),
    ".pka_predictor": ("PKaPredictorSignals", "PKaPredictorWorker"),
    ".permeability_worker": ("PermeabilityPredictorSignals", "PermeabilityPredictorWorker"),
    ".aizynthfinder_worker": ("AizynthFinderSignals", "AizynthFinderWorker"),
    ".biotransformer_worker": ("BiotransformerSignals", "BiotransformerWorker"),
    ".protomer_generator": ("ProtomerGeneratorSignals", "ProtomerGeneratorWorker"),
    ".protonate_worker": ("ProtonateSignals", "ProtonateWorker"),
    ".pdbqt_generator": ("PdbqtGenSignals", "PdbqtGenRequest", "PdbqtGeneratorWorker"),
    ".conforge_worker": ("ConforgeConformerWorker",),
    ".openbabel_confab_worker": ("SystematicConformerWorker",),
    ".protein_msa": ("MafftAlignSignals", "MafftAlignWorker"),
    ".fragment_decomposition": ("FragmentDecompositionWorker",),
    ".fragment_recomposition": ("FragmentRecompositionWorker",),
    ".mmp_worker": ("MmpAnalysisWorker",),
    ".sali_worker": ("SaliAnalysisWorker",),
    ".reaction_enumeration": ("ReactionEnumerationWorker",),
    ".rgroup_decomposition": ("RGroupDecompositionWorker",),
    ".central_ring_decomposition": ("CentralRingDecompositionWorker",),
    ".rgroup_enumeration": ("RGroupEnumerationWorker",),
    ".free_wilson_worker": ("FreeWilsonWorker",),
    ".hansch_worker": ("HanschWorker",),
    ".signals": (
        "BulkSimilaritySignals",
        "DiverseSubsetSignals",
        "FilterApplySignals",
        "FPSimilaritySignals",
        "PharmacophoreScreenSignals",
        "SessionOpenSignals",
        "SessionSaveSignals",
        "SqliteRebuildSignals",
        "SubstructureFilterSignals",
        "WorkerSignals",
    ),
    ".session_save": ("SessionOpenWorker", "SessionSaveWorker"),
    ".sqlite_rebuild": ("SqliteRebuildWorker",),
    ".filter_apply": ("FilterApplyWorker",),
    ".substructure_align": ("SubstructureAlignWorker",),
    ".substructure_filter": ("SubstructureFilterWorker",),
}

_MODULE_FOR_EXPORT: dict[str, str] = {
    name: module for module, names in _LAZY_EXPORT_MODULES.items() for name in names
}


def __getattr__(name: str) -> Any:
    module_name = _MODULE_FOR_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name, __package__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_MODULE_FOR_EXPORT))


__all__ = [
    "CalcWorker",
    "BulkSimilarityResult",
    "BulkSimilaritySignals",
    "BulkSimilarityWorker",
    "ClusterExploreWorker",
    "ClusterWorker",
    "CommonCoreWorker",
    "ConformerGenParams",
    "ConformerGenerationWorker",
    "SuperposeConformersWorker",
    "SuperposeStructuresWorker",
    "SuperposeParams",
    "SuperposeStructuresParams",
    "CustomCalcWorker",
    "DiverseSubsetSignals",
    "DiverseSubsetWorker",
    "build_diverse_subset_pool",
    "ExportWorker",
    "FilterApplySignals",
    "FilterApplyWorker",
    "FastPrepareWorker",
    "FragmentDecompositionWorker",
    "FragmentRecompositionWorker",
    "MmpAnalysisWorker",
    "SaliAnalysisWorker",
    "ReactionEnumerationWorker",
    "FPSimilaritySignals",
    "FPSimilarityWorker",
    "PharmacophoreScreenSignals",
    "PharmacophoreScreenWorker",
    "SIMILARITY_FP_TYPE_LABELS",
    "SIMILARITY_METRIC_LABELS",
    "pairwise_fingerprint_similarity",
    "PKaPredictorSignals",
    "PKaPredictorWorker",
    "PermeabilityPredictorSignals",
    "PermeabilityPredictorWorker",
    "AizynthFinderSignals",
    "AizynthFinderWorker",
    "BiotransformerSignals",
    "BiotransformerWorker",
    "ProtomerGeneratorSignals",
    "ProtomerGeneratorWorker",
    "Render2DBatchHeldJob",
    "Render2DBatchProcessWorker",
    "RenderWorker",
    "CentralRingDecompositionWorker",
    "RGroupDecompositionWorker",
    "RGroupEnumerationWorker",
    "FreeWilsonWorker",
    "HanschWorker",
    "SessionSaveSignals",
    "SessionSaveWorker",
    "SqliteRebuildSignals",
    "SqliteRebuildWorker",
    "SubstructureAlignWorker",
    "SubstructureFilterSignals",
    "SubstructureFilterWorker",
    "AddExplicitHydrogensWorker",
    "RemoveExplicitHydrogensWorker",
    "NeutralizeWorker",
    "UniversalLoadWorker",
    "DisconnectFragmentsWorker",
    "WorkerSignals",
    "ProtonateSignals",
    "ProtonateWorker",
    "PdbqtGenSignals",
    "PdbqtGenRequest",
    "PdbqtGeneratorWorker",
    "SystematicConformerWorker",
    "ConforgeConformerWorker",
    "MafftAlignSignals",
    "MafftAlignWorker",
    "describe_custom_calc_error",
    "fingerprint_bitvect_for_ui_choice",
    "materialize_pool_fingerprints",
    "maxmin_diverse_pick_bulk",
    "maxmin_diverse_pick_indices",
    "maxmin_diverse_pick_lazy",
    "run_diverse_subset_pick",
    "format_confs_table_cell",
    "pack_confs_cell",
    "run_conformer_generation",
    "run_superpose_conformers",
    "run_superpose_structures",
    "align_structure_onto_reference",
    "run_conformer_rmsd",
    "run_strain_energy",
    "strain_overlay_for_mol",
    "strain_overlay_for_mols",
    "strain_overlay_for_blocks_b64",
]
