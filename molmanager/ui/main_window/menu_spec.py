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

"""Declarative main-window menu tree.

This module is Qt-free: it describes labels, slots, hotkeys, and nesting.
``menu_builder.install_menu_specs`` turns the tree into ``QAction`` / ``QMenu``
widgets. Tests can assert structure with ``menu_outline`` without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KIND_ACTION = "action"
KIND_SEPARATOR = "separator"
KIND_SUBMENU = "submenu"
KIND_UNDO = "undo"
KIND_REDO = "redo"
KIND_SETTINGS = "settings"


@dataclass(frozen=True)
class MenuItem:
    """One menubar entry: an action, separator, submenu, or install hook."""

    kind: str = KIND_ACTION
    title: str = ""
    slot: str | None = None
    args: tuple[Any, ...] = ()
    tooltip: str = ""
    hotkey: str | None = None
    attr: str | None = None
    enabled: bool = True
    add_to_window: bool = False
    items: tuple[MenuItem, ...] = ()
    tooltips_visible: bool = False
    about_to_show: str | None = None
    call_with_window: str | None = None


def action(
    title: str,
    slot: str | None = None,
    *,
    tooltip: str = "",
    hotkey: str | None = None,
    attr: str | None = None,
    enabled: bool = True,
    add_to_window: bool = False,
    args: tuple[Any, ...] = (),
    call_with_window: str | None = None,
) -> MenuItem:
    """Leaf menu action bound to a window method or a known dialog opener."""
    return MenuItem(
        kind=KIND_ACTION,
        title=title,
        slot=slot,
        args=args,
        tooltip=tooltip,
        hotkey=hotkey,
        attr=attr,
        enabled=enabled,
        add_to_window=add_to_window,
        call_with_window=call_with_window,
    )


def submenu(
    title: str,
    *items: MenuItem,
    tooltips_visible: bool = False,
    attr: str | None = None,
    about_to_show: str | None = None,
) -> MenuItem:
    """Nested menu. *tooltips_visible* matches ``QMenu.setToolTipsVisible``."""
    return MenuItem(
        kind=KIND_SUBMENU,
        title=title,
        items=items,
        tooltips_visible=tooltips_visible,
        attr=attr,
        about_to_show=about_to_show,
    )


SEPARATOR = MenuItem(kind=KIND_SEPARATOR)
UNDO = MenuItem(kind=KIND_UNDO, hotkey="edit.undo", add_to_window=True)
REDO = MenuItem(kind=KIND_REDO, hotkey="edit.redo", add_to_window=True)
SETTINGS = MenuItem(kind=KIND_SETTINGS)
HELP_MENU = submenu(
    "&Help",
    action(
        "&User Guide",
        call_with_window="user_guide",
        hotkey="help.user_guides",
        attr="_act_user_guide",
        add_to_window=True,
        tooltip="Open MolManager help (F1).",
    ),
    action(
        "&Citations",
        call_with_window="citations",
        hotkey="help.citations",
        attr="_act_citations",
        add_to_window=True,
        tooltip="Open papers and licenses for tools used in MolManager.",
    ),
    attr="_help_menu",
)


def _plain(title: str) -> str:
    return title.replace("&", "")


def menu_outline(items: tuple[MenuItem, ...] | list[MenuItem]) -> list[object]:
    """Nested labels for tests. Separators are ``""``; ampersands are stripped."""
    out: list[object] = []
    for item in items:
        if item.kind == KIND_SEPARATOR:
            out.append("")
        elif item.kind == KIND_SETTINGS:
            out.append("Settings")
        elif item.kind == KIND_UNDO:
            out.append("Undo")
        elif item.kind == KIND_REDO:
            out.append("Redo")
        elif item.kind == KIND_SUBMENU:
            out.append({_plain(item.title): menu_outline(item.items)})
        else:
            out.append(_plain(item.title))
    return out


def find_submenu(items: tuple[MenuItem, ...], title: str) -> MenuItem:
    """Return the named submenu among *items* (ampersands ignored)."""
    want = _plain(title)
    for item in items:
        if item.kind == KIND_SUBMENU and _plain(item.title) == want:
            return item
    raise KeyError(title)


MAIN_WINDOW_MENUS: tuple[MenuItem, ...] = (
    submenu(
        "&File",
        action("&Open File...", "open_file_dialog", hotkey="file.open"),
        submenu(
            "Open &Recent",
            tooltips_visible=True,
            attr="_recent_menu",
            about_to_show="_populate_recent_menu",
        ),
        action("&Save File...", "run_export", hotkey="file.export_all", args=(False,)),
        action("Save Selected...", "run_export", args=(True,)),
        action("Import &Data...", "open_import_file_dialog"),
        SEPARATOR,
        submenu(
            "&Session",
            action("&Open Session…", "open_session_file", hotkey="file.open_session"),
            action("&Save Session…", "save_session_as", hotkey="file.save_session"),
            action("Save Selected to Session…", "save_selected_to_session"),
            action("&New Session", "new_session"),
            action("&Duplicate Session", "duplicate_session"),
            action(
                "Send Selected to New Session",
                "send_selected_to_new_session",
                tooltip="Open a new window that contains only the selected rows.",
            ),
            action("Close Session", "close_session", hotkey="file.close_session"),
            tooltips_visible=True,
        ),
    ),
    submenu(
        "&Edit",
        UNDO,
        REDO,
        SEPARATOR,
        action("&Copy", "edit_copy", hotkey="edit.copy"),
        action("&Paste", "edit_paste", hotkey="edit.paste"),
        SEPARATOR,
        action(
            "Find and &Replace…",
            "toggle_find_replace_panel",
            hotkey="edit.find_replace",
            tooltip=(
                "Open or hide Find and Replace (Ctrl+H). "
                "Text, wildcards (* and ?), or comparisons (>10, empty) in editable columns. "
                "ID, Structure, and image columns are skipped."
            ),
        ),
        SEPARATOR,
        action(
            "Invert Selection",
            "invert_table_selection",
            hotkey="edit.invert_selection",
            tooltip=(
                "Select all rows that are not currently selected "
                "(entire table, including rows hidden by filters)."
            ),
        ),
        action(
            "Clear Selection",
            "clear_table_selection",
            hotkey="edit.clear_selection",
            tooltip="Clear the current cell/row selection (Ctrl+Shift+D).",
        ),
        action(
            "Delete &Selection",
            "edit_delete_selection",
            hotkey="edit.delete_selection",
            tooltip=(
                "Delete selected rows, selected columns, or cell values, depending on the "
                "selection. When both rows and columns are selected, you choose which to delete."
            ),
        ),
        tooltips_visible=True,
    ),
    submenu(
        "&Tools",
        submenu(
            "Query &Database",
            action("PubChem…", "open_pubchem"),
            action("ChEMBL…", "open_chembl"),
            action(
                "Vendors…",
                "open_vendor_query",
                tooltip=(
                    "Look up chemical vendors, product IDs, and product pages for the query "
                    "structures. Structures with no vendor are omitted."
                ),
            ),
            action("Patents…", "open_patent_query"),
            SEPARATOR,
            action("SQL…", "open_external_db"),
            tooltips_visible=True,
        ),
        SEPARATOR,
        submenu(
            "&Random",
            action(
                "Number…",
                "open_random_number_dialog",
                tooltip=(
                    "Fill a column with random numbers (uniform, integer, or normal) "
                    "for all or selected rows."
                ),
            ),
            action(
                "Molecule…",
                "open_random_molecule_dialog",
                tooltip=(
                    "Fetch random small molecules from ChEMBL, PubChem, or ZINC and add them "
                    "to the table."
                ),
            ),
            tooltips_visible=True,
        ),
        action(
            "Calculator…",
            "open_calculator",
            hotkey="tools.calculator",
            attr="_act_custom_calc",
            tooltip="Add a numeric column from a math expression using existing column names (e.g. sqrt, log10, exp).",
        ),
        action(
            "Macros…",
            "open_macros",
            hotkey="tools.macros",
            tooltip=(
                "Run a saved sequence of descriptors, a calculator column, filters, "
                "protonation, and reaction enumeration."
            ),
        ),
        action(
            "Potency Standardization…",
            "open_potency_standardization",
            tooltip=(
                "Convert an activity column to nM or uM, with optional pActivity. "
                "Mass/volume units use molecular weight. "
                "IC50 can become Ki with Cheng–Prusoff when assay concentrations are known."
            ),
        ),
        action(
            "&Notepad",
            "open_notepad",
            tooltip=(
                "Open a floating notepad for session notes. Dock it like a plot or browser. "
                "Size, color, and style stay independent of Settings → GUI → Font."
            ),
        ),
        SEPARATOR,
        action(
            "&Sketcher…",
            "open_sketcher",
            hotkey="tools.sketcher",
            tooltip="Open the structure sketcher to draw or edit molecules.",
        ),
        action(
            "Drug Design Studio…",
            "open_design_studio",
            tooltip=(
                "Open a sketcher with a live descriptor and druglike MPO strip in its own window. "
                "Dock it beside the table from the window footer. "
                "An empty SAR Matrix cell builds that analog here."
            ),
        ),
        tooltips_visible=True,
    ),
    submenu(
        "&Chemistry",
        action(
            "Calculate Descriptors…",
            "open_calc",
            hotkey="tools.calculate_descriptors",
            tooltip=(
                "Compute RDKit molecular descriptors and structural-alert catalogs, "
                "and append them as columns (selected or visible rows)."
            ),
        ),
        SEPARATOR,
        submenu(
            "&Prepare Structures",
            action(
                "Fast Prepare…",
                "run_fast_prepare",
                tooltip=(
                    "Disconnect largest fragment, optionally neutralize, and redraw 2D "
                    "images in one background job."
                ),
            ),
            SEPARATOR,
            action(
                "Disconnect Largest Fragments…",
                "run_disconnect_fragments",
                tooltip=(
                    "Split disconnected structure fragments into separate rows, "
                    "keeping the heaviest fragment."
                ),
            ),
            submenu(
                "Protonate",
                action(
                    "Protonate…",
                    "run_protonate",
                    tooltip=(
                        "Generate the dominant protomer (Uni-pKa) into a column and "
                        "optionally render it like Structure."
                    ),
                ),
                action(
                    "Generate Protomers…",
                    "open_protomer_generator",
                    tooltip="Enumerate protomers or tautomers from structures and add results to the table.",
                ),
                action(
                    "Neutralize…",
                    "run_neutralize",
                    tooltip=(
                        "Adjust protonation so the net formal charge is zero "
                        "(RDKit Uncharger); updates the target column."
                    ),
                ),
                tooltips_visible=True,
            ),
            submenu(
                "Explicit Hydrogens",
                action(
                    "Add…",
                    "run_add_explicit_hydrogens",
                    tooltip="Expand implicit hydrogens to explicit H atoms in the target column (RDKit AddHs).",
                ),
                action(
                    "Remove…",
                    "run_remove_explicit_hydrogens",
                    tooltip="Remove explicit H atoms from structures in the target column (RDKit RemoveHs).",
                ),
                tooltips_visible=True,
            ),
            action(
                "Render 2D…",
                "run_render_2d_structures",
                hotkey="tools.render_2d",
                tooltip=(
                    "Regenerate 2D structure drawings for selected rows as a background "
                    "batch (see Log)."
                ),
            ),
            action(
                "Align to Substructure…",
                "run_align_substructure",
                tooltip=(
                    "Redraw matching rows so a substructure you supply sits in one "
                    "shared orientation. Rows that do not match are left unchanged."
                ),
            ),
            tooltips_visible=True,
        ),
        submenu(
            "&Conformations",
            submenu(
                "&Generate",
                action(
                    "Stochastic…",
                    "open_generate_conformations",
                    tooltip=(
                        "Build ensembles with RDKit ETKDG (stochastic distance geometry), "
                        "then minimize and prune."
                    ),
                ),
                action(
                    "Systematic…",
                    "open_systematic_conformations",
                    tooltip="Build ensembles with Open Babel Confab (systematic torsion search).",
                ),
                action(
                    "CONFORGE…",
                    "open_conforge_conformations",
                    tooltip=(
                        "Build ensembles with CONFORGE (CDPKit knowledge-based fragment "
                        "and torsion sampling)."
                    ),
                ),
                tooltips_visible=True,
            ),
            SEPARATOR,
            action(
                "&Superpose…",
                "open_superpose",
                tooltip=(
                    "Overlay conformers within a row or structures across rows, "
                    "in 3D (spatial) or 2D (topological)."
                ),
            ),
            action(
                "Screen Pharmacophore…",
                "open_pharmacophore_screen",
                tooltip=(
                    "Find table molecules whose conformers match a 3D pharmacophore "
                    "(RDKit feature types and pairwise distances)."
                ),
            ),
            tooltips_visible=True,
        ),
        submenu(
            "&Substructure",
            action(
                "Bemis–Murcko…",
                "open_bemis_murcko",
                tooltip=(
                    "Write the Bemis–Murcko scaffold, framework, ring systems, "
                    "and how many rows share each scaffold."
                ),
            ),
            action(
                "Common Core…",
                "open_common_core",
                tooltip=(
                    "Find a maximum common substructure over the rows, "
                    "and mark the structures that do not contain it."
                ),
            ),
            tooltips_visible=True,
        ),
        submenu(
            "&Predict",
            action(
                "pKa…",
                "open_pka_predictor",
                tooltip="Estimate ionization / pKa-related properties when the predictor is available.",
            ),
            action(
                "Permeability…",
                "open_permeability_predictor",
                tooltip=(
                    "Predict Caco-2 and MDCK permeability / efflux endpoints "
                    "(optional Chemprop install)."
                ),
            ),
            submenu(
                "Metabolites",
                action(
                    "Predict…",
                    "open_biotransformer_predictor",
                    tooltip="Predict metabolite structures with a local BioTransformer JAR.",
                ),
                action(
                    "Viewer",
                    "open_metabolite_viewer",
                    tooltip="Open the metabolite browser when Predict Metabolites results are in the table.",
                    attr="_act_metabolite_viewer",
                    enabled=False,
                ),
                tooltips_visible=True,
            ),
            tooltips_visible=True,
            about_to_show="_sync_predict_viewer_actions",
        ),
        submenu(
            "Structure &Decomposition",
            action(
                "Core-Based Decomposition…",
                "open_core_based_decomposition",
                tooltip="Decompose structures against a labeled core scaffold (substituent columns).",
            ),
            action(
                "BRICS Decomposition…",
                "open_brics_decomposition",
                tooltip="Split structures into BRICS retrosynthetic fragments (new SMILES columns).",
            ),
            action(
                "RECAP Decomposition…",
                "open_recap_decomposition",
                tooltip="Split structures into RECAP retrosynthetic fragments (new SMILES columns).",
            ),
            tooltips_visible=True,
        ),
        submenu(
            "Structure &Enumeration",
            action(
                "R-Group Enumeration…",
                "open_rgroup_enumeration",
                tooltip=(
                    "Attach building-block lists to a core with numbered * points and append the "
                    "products. The same property limits used for fragment recomposition can cap the set."
                ),
            ),
            action(
                "BRICS Recomposition…",
                "open_brics_recomposition",
                tooltip="Combine BRICS fragment columns into new product structures (new rows).",
            ),
            action(
                "RECAP Recomposition…",
                "open_recap_recomposition",
                tooltip="Combine RECAP fragment columns into new product structures (new rows).",
            ),
            action(
                "Reaction Based Enumeration…",
                "open_reaction_enumeration",
                tooltip=(
                    "Run a named reaction (Suzuki, Buchwald, amide coupling, etc.) across two reactant "
                    "pools from structure files or pasted SMILES, then append products to the table "
                    "and/or an SDF file."
                ),
            ),
            tooltips_visible=True,
        ),
        action(
            "REINVENT Sampling…",
            "open_reinvent_sampling",
            tooltip=(
                "Sample molecules with a local REINVENT 4 install "
                "(de novo, R-groups, linkers, or similar molecules) and append them."
            ),
        ),
        action(
            "Extract Reaction Info…",
            "open_reaction_extract",
            tooltip=(
                "Split a reaction SMARTS / SMIRKS column into individual reactant and/or "
                "product columns."
            ),
        ),
        submenu(
            "&Retrosynthesis",
            action(
                "Search…",
                "open_aizynthfinder",
                tooltip=(
                    "Plan routes with a local AiZynthFinder install "
                    "(Settings → Configure → AiZynthFinder)."
                ),
            ),
            tooltips_visible=True,
        ),
        tooltips_visible=True,
    ),
    submenu(
        "&Protein",
        action(
            "&Viewer",
            "open_protein_viewer",
            tooltip="Load a PDB, mmCIF, or other crystallographic file and inspect chains in 3D.",
        ),
        action(
            "&Sequence…",
            "open_protein_sequence",
            tooltip="Align amino-acid sequences with MAFFT (FASTA, paste, or Protein Viewer chains).",
        ),
        submenu(
            "&Dock Ligand",
            submenu(
                "Prepare",
                action(
                    "PDBQT…",
                    "open_dock_prepare",
                    tooltip=(
                        "Generate receptor and/or ligand PDBQT (receptor PDB; ligand SDF, PDB, "
                        "SMILES, or table rows)."
                    ),
                ),
                action(
                    "Receptor PDB…",
                    "open_dock_prepare_pdb",
                    tooltip=(
                        "Clean a receptor PDB with PDBFixer (remove ligands/waters, add atoms "
                        "and hydrogens) before PDBQT conversion or docking."
                    ),
                ),
                tooltips_visible=True,
            ),
            SEPARATOR,
            action(
                "Gnina…",
                "open_gnina_dock",
                tooltip="Run Gnina as a file-based CLI (CNN scoring; no table writeback).",
            ),
            SEPARATOR,
            action(
                "Pose Browser",
                "open_dock_results_viewer",
                tooltip="Show the pose browser for the last docking run, even after it has been closed.",
                attr="_act_dock_viewer",
                enabled=False,
            ),
            tooltips_visible=True,
        ),
        action(
            "Interaction Fingerprint…",
            "open_interaction_fingerprint",
            tooltip=(
                "Type residue contacts for each stored pose and write an interaction "
                "fingerprint plus the contacted residue list."
            ),
        ),
        tooltips_visible=True,
    ),
    submenu(
        "&Data",
        submenu(
            "&Table",
            submenu(
                "&Operations",
                action(
                    "Add &Row…",
                    "add_blank_table_row",
                    hotkey="data.add_row",
                    tooltip="Append one or more empty rows at the bottom of the table.",
                ),
                action(
                    "Add &Column…",
                    "add_blank_table_column",
                    hotkey="data.add_column",
                    tooltip="Append one or more empty data columns. You choose the name and count.",
                ),
                SEPARATOR,
                action(
                    "Split Column…",
                    "open_split_column_dialog",
                    hotkey="data.split_column",
                    tooltip="Split a delimited column (comma, tab, space, semicolon, …) into new columns.",
                ),
                action(
                    "Join Columns…",
                    "open_join_columns_dialog",
                    hotkey="data.join_columns",
                    tooltip="Join two columns into one new column with a chosen delimiter.",
                ),
                tooltips_visible=True,
            ),
            action("Statistics…", "open_data_analysis", hotkey="data.analyze_table"),
        ),
        submenu(
            "&Lists",
            action(
                "Add Selected to List…",
                "add_selected_to_list",
                hotkey="data.add_to_list",
                tooltip="Save the selected rows as a named list (Ctrl+L). An existing name adds to that list.",
                attr="_act_add_selected_to_list",
            ),
            action(
                "Remove Selected from List…",
                "remove_selected_from_list",
                tooltip="Remove the selected rows from an existing list. The table rows are kept.",
                attr="_act_remove_selected_from_list",
            ),
            MenuItem(kind=KIND_SEPARATOR, attr="_act_lists_footer_separator"),
            action(
                "Manage Lists…",
                "manage_row_lists",
                tooltip="Rename or delete named row lists.",
                attr="_act_manage_lists",
            ),
            attr="_lists_menu",
            about_to_show="_rebuild_lists_menu",
            tooltips_visible=True,
        ),
        SEPARATOR,
        submenu(
            "&QSAR",
            action(
                "Generate Model…",
                "open_qsar_dialog",
                tooltip="Train regression or classification models on activity vs descriptors or fingerprints.",
            ),
            action(
                "AutoQSAR…",
                "open_auto_qsar_dialog",
                tooltip=(
                    "Search descriptors and models for an activity column, then write predictions."
                ),
            ),
            action(
                "CoMSIA…",
                "open_comsia_dialog",
                tooltip=("Fit a 3D CoMSIA model on aligned poses and write predicted activities."),
            ),
            tooltips_visible=True,
        ),
        action(
            "MPO Scoring…",
            "open_mpo_scoring_dialog",
            tooltip=(
                "Score rows with linear, Gaussian, or step desirability functions and combine "
                "into an overall MPO score."
            ),
        ),
        submenu(
            "Simila&rity",
            action(
                "Fingerprint Similarity...",
                "open_fp_similarity",
                hotkey="tools.fingerprint_similarity",
                tooltip="Search the table by 2D fingerprint similarity to a query structure.",
            ),
            action(
                "Diverse Subset…",
                "open_diverse_subset",
                tooltip=(
                    "Pick a maximally diverse subset of compounds "
                    "(MaxMin on fingerprint Tanimoto distance)."
                ),
            ),
            action(
                "Cluster…",
                "open_cluster_dialog",
                hotkey="data.cluster",
                tooltip=(
                    "Cluster compounds by fingerprint, numeric columns, or both "
                    "(K-Means, Butina, sphere exclusion, etc.)."
                ),
            ),
            action(
                "Binning…",
                "open_binning_dialog",
                hotkey="data.binning",
                tooltip=(
                    "Assign numeric values to bins and write the range and classification "
                    "into separate columns."
                ),
            ),
            tooltips_visible=True,
        ),
        SEPARATOR,
        action(
            "SALI…",
            "open_sali_dialog",
            tooltip=(
                "Plot fingerprint similarity vs |Δactivity| or |Δselectivity| colored by SALI "
                "(|Δ| / (1 − similarity)). Selectivity is on-target minus off-target "
                "on a pIC50 or pKi scale."
            ),
        ),
        action(
            "&MMP…",
            "open_mmp_dialog",
            tooltip=(
                "Find matched molecular pairs (RDKit MMPA) and open the transform ledger "
                "ranked by support and activity effect."
            ),
        ),
        action(
            "Free-&Wilson…",
            "open_free_wilson_dialog",
            tooltip=(
                "Fit an additive Free-Wilson model on a shared core and list predicted "
                "activities for missing substituent combinations."
            ),
        ),
        action(
            "&Hansch…",
            "open_hansch_dialog",
            tooltip=(
                "Fit a Hansch equation of activity versus π, σ, and a steric constant "
                "on a shared core."
            ),
        ),
        action(
            "SAR Matrix…",
            "open_sar_matrix_dialog",
            tooltip=(
                "Pivot R-group columns into an R1 × R2 grid colored by activity. "
                "A third substituent becomes pages. Click a cell to select its rows."
            ),
        ),
        SEPARATOR,
        submenu(
            "&MedChem Plots",
            action("BOILED-Egg…", "open_boiled_egg_plot"),
            action("Golden Triangle…", "open_golden_triangle_plot"),
            action(
                "LipE…",
                "open_lipe_plot",
                tooltip=(
                    "Plot pActivity against LogP with lines of constant "
                    "lipophilic efficiency (LipE = pActivity − LogP)."
                ),
            ),
            tooltips_visible=True,
        ),
        submenu(
            "&Dimensionality Reduction",
            action("Principal Component Analysis…", "open_pca_dialog"),
            action("t-SNE Visualization…", "open_tsne_dialog"),
            action("UMAP Visualization…", "open_umap_dialog"),
            action("Self-Organizing Map…", "open_som_dialog"),
            tooltips_visible=True,
        ),
        SEPARATOR,
        action(
            "&Plotter…",
            "open_plot",
            hotkey="data.plotter",
            tooltip="Open the plotter or show the docked plot panel.",
        ),
        SEPARATOR,
        submenu(
            "&Filter",
            action(
                "Toggle Panel",
                "toggle_filter_panel",
                hotkey="tools.toggle_filter_panel",
                attr="_act_toggle_filter_panel",
                add_to_window=True,
                tooltip="Show or hide the filter panel (Ctrl+Shift+L).",
            ),
            SEPARATOR,
            action(
                "Add Substructure",
                "add_substructure_filter_card",
                tooltip="Add a filter card that matches a SMARTS substructure in the Structure column.",
            ),
            action(
                "Add Slider",
                "add_filter_card",
                tooltip="Add a numeric range slider filter for a column.",
            ),
            action(
                "Add Text",
                "add_text_filter_card",
                tooltip="Add a text contains / equals filter for a column.",
            ),
            action(
                "Add Category",
                "add_category_filter_card",
                tooltip="Add a categorical multi-select filter for a column.",
            ),
            SEPARATOR,
            action(
                "Enable All Filters",
                "enable_all_filters_keep_panel",
                tooltip="Turn on every filter card in the panel.",
            ),
            action(
                "Disable All Filters",
                "disable_all_filters_keep_panel",
                tooltip=(
                    "Turn off every filter card. Cards stay in the panel; use On on each card "
                    "to enable again."
                ),
            ),
            action(
                "Delete All Filters",
                "delete_all_filters_from_panel",
                tooltip="Remove every filter card from the panel.",
            ),
            tooltips_visible=True,
        ),
        action(
            "&Search…",
            "toggle_table_search_panel",
            hotkey="tools.search",
            tooltip="Open or hide the in-table search panel (Ctrl+F). Queries stay until deleted with −.",
        ),
        SEPARATOR,
        action(
            "&Browser…",
            "open_selection_browser",
            hotkey="file.browser",
            tooltip="Open the selection browser to review and act on selected rows. "
            "Right-click a structure for Browser; settings pick RDKit 2D, 3Dmol 2D, or 3Dmol 3D.",
        ),
        tooltips_visible=True,
    ),
    SETTINGS,
)
