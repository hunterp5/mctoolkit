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

"""Qt signal objects shared by background workers."""

from PyQt5.QtCore import QObject, pyqtSignal


def emit_partial_results_if_cancelled(
    signals: "WorkerSignals",
    tool_label: str,
    done: int,
    total: int,
    cancelled: bool,
) -> None:
    """Emit ``partial_results`` before the finish signal so the UI can show a cancel notice."""
    if not cancelled:
        return
    try:
        signals.partial_results.emit(tool_label, int(done), max(1, int(total)))
    except Exception:
        pass


class WorkerSignals(QObject):
    """Signals from background workers to the main window (single QObject for simple wiring)."""

    # --- Load + 2D render pipeline ---
    # mols_loaded: (batch, headers_or_empty, is_first_batch, is_last_batch)
    # batch entries are Chem.Mol (SDF/MOL) or dict[str,str] cell maps (text-first CSV/TSV).
    mols_loaded = pyqtSignal(list, list, bool, bool)
    # file_load_failed: (ingest_generation, user_message). Not a successful empty load.
    file_load_failed = pyqtSignal(int, str)
    # Emitted on the UI thread before bulk read when multiple structure columns exist; worker waits.
    structure_source_probe = pyqtSignal(list)
    # Last int: render_batch_session (0 = single / non-batch; non-zero must match app accept id)
    rendered = pyqtSignal(int, dict, bytes, bool, int, int, int)
    # Batch 2D render: (rows, render_batch_session) where rows are (oid, png, ok, w, h).
    # Batch renders never carry mol properties.
    rendered_batch = pyqtSignal(list, int)

    # --- Batch chemistry / tools (disconnect, descriptors, conformers, custom calc, export) ---
    disconnect_fragments_finished = pyqtSignal(list)
    neutralized = pyqtSignal(list)
    # Fast Prepare (fused disconnect, optional neutralize): list of
    # (oid, mol_blob_bytes, smaller_fragments_text, canonical_smiles_or_empty)
    fast_prepared = pyqtSignal(list)
    explicit_hydrogens_added = pyqtSignal(list)
    explicit_hydrogens_removed = pyqtSignal(list)
    calculated = pyqtSignal(list, list)
    # list of (oid, mol_or_None, confs_cell_json_str)
    conformers_finished = pyqtSignal(list)
    # list of (oid, mol_or_None, superpose_cell_str) — same packed format as ``confs`` when successful
    superpose_finished = pyqtSignal(list)
    # dict: ref_oid, geometry, results list of (oid, mol_or_None, meta)
    superpose_structures_finished = pyqtSignal(object)
    custom_calc = pyqtSignal(list)
    export_finished = pyqtSignal(str)
    # Core-based decomposition: list of (oid, {header: value}), then ordered new column names
    rgroup_decomp_finished = pyqtSignal(list, list)
    rgroup_decomp_failed = pyqtSignal(str)
    # BRICS / RECAP recomposition: product SMILES list, tool_title
    fragment_recomp_finished = pyqtSignal(list, str, int)
    fragment_recomp_failed = pyqtSignal(str, str)
    # BRICS / RECAP: (rows, headers, tool_title)
    fragment_decomp_finished = pyqtSignal(list, list, str)
    fragment_decomp_failed = pyqtSignal(str, str)
    # Reaction-based enumeration: ReactionEnumerationJobResult
    reaction_enum_finished = pyqtSignal(object)
    reaction_enum_failed = pyqtSignal(str, str)
    # Matched molecular pairs: (pairs, activity_column)
    mmp_finished = pyqtSignal(list, str)
    mmp_failed = pyqtSignal(str)
    # Free-Wilson: FreeWilsonResult
    free_wilson_finished = pyqtSignal(object)
    free_wilson_failed = pyqtSignal(str)
    # Activity cliff map: (pairs, activity_column, x_mode)
    activity_cliff_finished = pyqtSignal(list, str, str)
    activity_cliff_failed = pyqtSignal(str)
    # MMP pair neighborhood network: (pairs, activity_column)
    mmp_neighborhood_finished = pyqtSignal(list, str)
    mmp_neighborhood_failed = pyqtSignal(str)
    # SALI landscape: (points, activity_column, fp_choice, metric)
    sali_finished = pyqtSignal(list, str, str, str)
    sali_failed = pyqtSignal(str)
    cluster_failed = pyqtSignal(str)
    # Exploratory clustering: list of dict rows (method, params, settings, metrics, notes)
    cluster_explore_finished = pyqtSignal(list)
    # --- Progress banner (message, done, total; total < 0 => indeterminate) ---
    tool_progress = pyqtSignal(str, int, int)
    # Partial results were emitted before cancellation (tool_label, done, total).
    partial_results = pyqtSignal(str, int, int)


class FPSimilaritySignals(QObject):
    """Completion signals for :class:`FPSimilarityWorker` (owned by the dialog, not global WorkerSignals)."""

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)


class PharmacophoreScreenSignals(QObject):
    """Completion signals for :class:`PharmacophoreScreenWorker` (owned by the dialog)."""

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)


class DiverseSubsetSignals(QObject):
    """Completion signals for :class:`DiverseSubsetWorker` (owned by the dialog)."""

    # picked oids; column_rows; cached fp count; newly computed fp count
    finished = pyqtSignal(list, list, int, int)
    failed = pyqtSignal(str)


class BulkSimilaritySignals(QObject):
    """Completion signals for :class:`BulkSimilarityWorker` (owned by the dialog)."""

    finished = pyqtSignal(object)  # BulkSimilarityResult
    failed = pyqtSignal(str)


class SubstructureFilterSignals(QObject):
    """Completion signals for :class:`SubstructureFilterWorker` (owned by the main window)."""

    finished = pyqtSignal(int, object)  # job_gen, list[(smarts, structure_source, frozenset[oid])]
    failed = pyqtSignal(int, str)  # job_gen, message


class FilterApplySignals(QObject):
    """Completion signals for :class:`FilterApplyWorker` (owned by the main window)."""

    finished = pyqtSignal(int, object)  # job_gen, frozenset[int] of matched oids
    failed = pyqtSignal(int, str)  # job_gen, message


class SqliteRebuildSignals(QObject):
    """Completion signals for :class:`SqliteRebuildWorker` (owned by the main window)."""

    finished = pyqtSignal(int, str)  # job_gen, path to rebuilt sqlite file
    failed = pyqtSignal(int, str)  # job_gen, message


class SessionSaveSignals(QObject):
    """Completion signals for :class:`SessionSaveWorker` (owned by the main window)."""

    finished = pyqtSignal(int, str)  # job_gen, path written
    failed = pyqtSignal(int, str)  # job_gen, message
