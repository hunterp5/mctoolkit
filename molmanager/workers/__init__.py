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

# ``chemistry_tools`` pulls in ``medchem_descriptors`` and must not load during ``workers``
# package init (e.g. ``ionization`` imports stay lazy from descriptor callables).
_CHEMISTRY_TOOLS_EXPORTS = frozenset(
    {
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
    }
)


def __getattr__(name: str) -> Any:
    if name in _CHEMISTRY_TOOLS_EXPORTS:
        ct = importlib.import_module(".chemistry_tools", __package__)
        return getattr(ct, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


from .bulk_similarity import BulkSimilarityResult, BulkSimilarityWorker
from .cluster_worker import ClusterExploreWorker, ClusterWorker
from .common_core import CommonCoreWorker
from .export_worker import ExportWorker
from ..chem.rdkit_fingerprints import SIMILARITY_FP_TYPE_LABELS, fingerprint_bitvect_for_ui_choice
from .diverse_subset_worker import (
    DiverseSubsetWorker,
    build_diverse_subset_pool,
    materialize_pool_fingerprints,
    maxmin_diverse_pick_bulk,
    maxmin_diverse_pick_indices,
    maxmin_diverse_pick_lazy,
    run_diverse_subset_pick,
)
from .fingerprint_similarity import (
    FPSimilarityWorker,
    SIMILARITY_METRIC_LABELS,
    pairwise_fingerprint_similarity,
)
from .pharmacophore_screen import PharmacophoreScreenWorker
from .fast_prepare import FastPrepareWorker
from .load_render import (
    AddExplicitHydrogensWorker,
    NeutralizeWorker,
    RemoveExplicitHydrogensWorker,
    Render2DBatchHeldJob,
    Render2DBatchProcessWorker,
    RenderWorker,
    STRUCTURE_PAYLOAD_TAG,
    UniversalLoadWorker,
    DisconnectFragmentsWorker,
)
from .pka_predictor import PKaPredictorSignals, PKaPredictorWorker
from .permeability_worker import PermeabilityPredictorSignals, PermeabilityPredictorWorker
from .som_worker import SomPredictorSignals, SomPredictorWorker
from .biotransformer_worker import BiotransformerSignals, BiotransformerWorker
from .protomer_generator import ProtomerGeneratorSignals, ProtomerGeneratorWorker
from .protonate_worker import ProtonateSignals, ProtonateWorker
from .pdbqt_generator import PdbqtGenSignals, PdbqtGenRequest, PdbqtGeneratorWorker
from .conforge_worker import ConforgeConformerWorker
from .openbabel_confab_worker import SystematicConformerWorker
from .protein_msa import MafftAlignSignals, MafftAlignWorker
from .fragment_decomposition import FragmentDecompositionWorker
from .fragment_recomposition import FragmentRecompositionWorker
from .mmp_worker import MmpAnalysisWorker
from .sali_worker import SaliAnalysisWorker
from .reaction_enumeration import ReactionEnumerationWorker
from .rgroup_decomposition import RGroupDecompositionWorker
from .rgroup_enumeration import RGroupEnumerationWorker
from .free_wilson_worker import FreeWilsonWorker
from .signals import (
    BulkSimilaritySignals,
    DiverseSubsetSignals,
    FilterApplySignals,
    FPSimilaritySignals,
    PharmacophoreScreenSignals,
    SessionSaveSignals,
    SqliteRebuildSignals,
    SubstructureFilterSignals,
    WorkerSignals,
)
from .session_save import SessionSaveWorker
from .sqlite_rebuild import SqliteRebuildWorker
from .filter_apply import FilterApplyWorker
from .substructure_align import SubstructureAlignWorker
from .substructure_filter import SubstructureFilterWorker

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
    "SomPredictorSignals",
    "SomPredictorWorker",
    "BiotransformerSignals",
    "BiotransformerWorker",
    "ProtomerGeneratorSignals",
    "ProtomerGeneratorWorker",
    "Render2DBatchHeldJob",
    "Render2DBatchProcessWorker",
    "RenderWorker",
    "STRUCTURE_PAYLOAD_TAG",
    "RGroupDecompositionWorker",
    "RGroupEnumerationWorker",
    "FreeWilsonWorker",
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
