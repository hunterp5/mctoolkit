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

"""User-facing tool names and recurring status copy (single place to tweak wording)."""

from ..services.column_labels import COLUMN_TANIMOTO_SIMILARITY as COLUMN_TANIMOTO_SIMILARITY

TOOLS_ARROW_RENDER_2D = "Tools → Render 2D"
TOOL_RENDER_2D = "Render 2D"
TOOL_CORE_DECOMP = "Core-Based Decomposition"
TOOL_BRICS_DECOMP = "BRICS Decomposition"
TOOL_RECAP_DECOMP = "RECAP Decomposition"
TOOL_BRICS_RECOMP = "BRICS Recomposition"
TOOL_RECAP_RECOMP = "RECAP Recomposition"
TOOL_CALCULATOR = "Calculator"
TOOL_ADD_EXPLICIT_HYDROGENS = "Add Explicit Hydrogens"
TOOL_REMOVE_EXPLICIT_HYDROGENS = "Remove Explicit Hydrogens"
TOOL_REACTION_ENUMERATION = "Reaction Based Enumeration"
TOOL_REACTION_EXTRACT = "Extract"
TOOL_MMP = "Matched Molecular Pairs"
TOOL_ACTIVITY_CLIFF_MAP = "Activity Cliffs"
TOOL_MMP_PAIR_NETWORK = "Pair Network"
TOOL_SALI_MAP = "SALI"
TOOL_RANDOM_NUMBER = "Random Number"
TOOL_RANDOM_MOLECULE = "Random Molecule"
TOOL_SPLIT_COLUMN = "Split Column"
TOOL_JOIN_COLUMNS = "Join Columns"
TOOL_PREDICT_SOM = "Predict SOM"
TOOL_PREDICT_METABOLITES = "Predict Metabolites"

# Column header when importing similarity hits (PubChem, ChEMBL, SureChEMBL) or adding FP similarity scores.
# Defined in services.column_labels; re-exported here for UI callers.

STRUCTURE_PENDING_HINT = f"No 2D structure yet.\nUse {TOOLS_ARROW_RENDER_2D} to draw."

STATUS_READY = "Ready"
STATUS_READY_RENDER_2D = f"Ready — use {TOOLS_ARROW_RENDER_2D} to refresh or redraw 2D images."

LOADING_DETAIL_AFTER_FILE_READ = (
    "File read; building table…\n2D structure images continue after the table is shown."
)
LOADING_DETAIL_READING_DISK = (
    "Reading file from disk…\n2D structure images continue after the table is shown."
)
LOADING_DETAIL_APPEND = (
    "Reading file from disk…\nNew rows are appended; 2D images continue after the table is shown."
)
LOADING_DETAIL_SESSION = (
    "Loading session…\n"
    "Restoring table, filters, and plots. 2D images continue after the workspace is shown."
)
LOADING_DETAIL_IDLE = (
    "Open a file or session to begin.\n"
    "The table and plot panes appear after data is loaded."
)
LOADING_DETAIL_PROTEIN_VIEWER = (
    "Loading structures…\nDrawing the 3D view. The window stays open while this finishes."
)
LOADING_DETAIL_PROTEIN_VIEWER_START = (
    "Starting 3D view…\nThe window stays open while the canvas starts."
)
LOADING_DETAIL_PROTEIN_STRUCTURE = (
    "Loading structure…\nDrawing the 3D view. The window stays open while this finishes."
)

DISCONNECT_FRAGMENTS_HELP = (
    "Split salts and multi-component entries, keep the largest fragment as the working molecule,\n"
    "and update SMILES / Fragments. The Structure column is redrawn from that largest fragment only "
    "(salt is never depicted there)."
)


def loaded_session_status(rows_n: int) -> str:
    return f"Loaded session ({rows_n} rows) — {TOOLS_ARROW_RENDER_2D} for images."


def loaded_sql_status(nrows: int) -> str:
    return f"Loaded {nrows} row(s) from SQL."
